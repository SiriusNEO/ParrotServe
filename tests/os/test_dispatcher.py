import parrot as P

from Parrot.parrot.os.session.session import Process
from parrot.os.tokenizer import Tokenizer
from Parrot.parrot.os.context.context_manager import MemorySpace
from Parrot.parrot.os.engine.engine_node import ExecutionEngine
from parrot.os.session.thread import Thread
from parrot.engine.config import EngineConfig
from parrot.os.context.context import Context
from parrot.os.thread_dispatcher import DispatcherConfig, ThreadDispatcher


@P.semantic_function()
def test(a: P.Input, b: P.Output):
    """This is a test {{a}} function {{b}}"""


def test_default_policy():
    dispatcher_config = DispatcherConfig(
        dag_aware=False,
        app_fifo=False,
        max_queue_size=1024,
    )

    # 4 identical engines
    tokenizer = Tokenizer()
    engine_config = EngineConfig(tokenizer="hf-internal-testing/llama-tokenizer")
    engines = {
        i: ExecutionEngine(engine_id=i, config=engine_config, tokenizer=tokenizer)
        for i in range(4)
    }

    # init dispatcher
    dispatcher = ThreadDispatcher(config=dispatcher_config, engines=engines)
    mem_space = MemorySpace()
    process = Process(
        pid=0,
        dispatcher=dispatcher,
        tokenizer=tokenizer,
        memory_space=mem_space,
    )

    # 8 threads
    call = test("a")
    process.rewrite_call(call)
    for i in range(8):
        thread = Thread(tid=i, process=process, call=call, context_id=0)
        dispatcher.push_thread(thread)

    dispatched_threads = dispatcher.dispatch()

    assert len(dispatched_threads) == 8

    # Expect results: dispatch threads averagely to all engines i.e. 2 threads per engine


@P.semantic_function()
def test_func_throughput(
    a: P.Input,
    b: P.Output(
        dispatch_annotation=P.DispatchAnnotation(requests_num_upperbound=64),
    ),
):
    """This is a test {{a}} function {{b}}"""


@P.semantic_function()
def test_func_latency(
    a: P.Input,
    b: P.Output(
        dispatch_annotation=P.DispatchAnnotation(requests_num_upperbound=3),
    ),
):
    """This is a test {{a}} function {{b}}"""


def test_dag_aware_policy():
    dispatcher_config = DispatcherConfig(
        dag_aware=True,
        app_fifo=False,
        max_queue_size=1024,
    )

    # 4 identical engines
    tokenizer = Tokenizer()
    engine_config = EngineConfig(tokenizer="hf-internal-testing/llama-tokenizer")
    engines = {
        i: ExecutionEngine(engine_id=i, config=engine_config, tokenizer=tokenizer)
        for i in range(4)
    }

    # init dispatcher
    dispatcher = ThreadDispatcher(config=dispatcher_config, engines=engines)
    mem_space = MemorySpace()
    process = Process(
        pid=0,
        dispatcher=dispatcher,
        tokenizer=tokenizer,
        memory_space=mem_space,
    )

    # 16 threads, with 8 throughput threads and 8 latency threads
    call1 = test_func_throughput("a")
    call2 = test_func_latency("a")
    process.rewrite_call(call1)
    process.rewrite_call(call2)
    for i in range(8):
        thread = Thread(tid=i, process=process, call=call1, context_id=0)
        dispatcher.push_thread(thread)
    for i in range(8, 16):
        thread = Thread(tid=i, process=process, call=call2, context_id=0)
        dispatcher.push_thread(thread)

    dispatched_threads = dispatcher.dispatch()

    assert len(dispatched_threads) == 16

    # Expect results: 8 throughput threads are dispatched to the same engine,
    # and 8 latency threads are dispatched averagely to the rest 3 engines.


def test_dispatcher_order():
    dispatcher_config = DispatcherConfig(
        dag_aware=False,
        app_fifo=False,
        max_queue_size=1024,
    )

    # 1 engine with threads_capacity=1
    tokenizer = Tokenizer()
    engine_config = EngineConfig(
        threads_capacity=1,
        tokens_capacity=99999,
        tokenizer="hf-internal-testing/llama-tokenizer",
    )
    engines = {
        0: ExecutionEngine(engine_id=0, config=engine_config, tokenizer=tokenizer)
    }

    # init dispatcher
    dispatcher = ThreadDispatcher(config=dispatcher_config, engines=engines)
    mem_space = MemorySpace()
    process = Process(
        pid=0,
        dispatcher=dispatcher,
        tokenizer=tokenizer,
        memory_space=mem_space,
    )

    # 4 threads with chain dependency
    outputs = [P.variable() for _ in range(8)]
    threads = [None] * 8
    next_input = "a"

    for i in range(4):
        idx = i * 2

        call = test(a=next_input, b=outputs[idx])

        # Rewrite call to make DAG
        process.rewrite_call(call)

        next_input = outputs[idx]
        thread = Thread(tid=idx, process=process, call=call, context_id=0)
        call.thread = thread
        threads[idx] = thread

    next_input = "a"

    for i in range(4):
        idx = i * 2 + 1

        call = test(a=next_input, b=outputs[idx])

        # Rewrite call to make DAG
        process.rewrite_call(call)

        next_input = outputs[idx]
        thread = Thread(tid=idx, process=process, call=call, context_id=0)
        call.thread = thread
        threads[idx] = thread

    # Push threads in reverse order
    for thread in threads[::-1]:
        dispatcher.push_thread(thread)

    for _ in range(8):
        dispatched_threads = dispatcher.dispatch()
        assert len(dispatched_threads) == 1, len(dispatched_threads)
        thread = dispatched_threads[0]
        thread.engine.remove_thread(thread)  # Free loc


def test_app_fifo():
    dispatcher_config = DispatcherConfig(
        dag_aware=False,
        app_fifo=True,
        max_queue_size=1024,
    )

    # 1 engine with threads_capacity=1
    tokenizer = Tokenizer()
    engine_config = EngineConfig(
        threads_capacity=1, tokenizer="hf-internal-testing/llama-tokenizer"
    )
    engines = {
        0: ExecutionEngine(engine_id=0, config=engine_config, tokenizer=tokenizer)
    }

    # init dispatcher
    dispatcher = ThreadDispatcher(config=dispatcher_config, engines=engines)
    mem_space = MemorySpace()
    process = Process(
        pid=0,
        dispatcher=dispatcher,
        tokenizer=tokenizer,
        memory_space=mem_space,
    )

    # 8 calls, each group of 2 calls with A->B dependency.
    threads = []
    for i in range(4):
        tid1 = i
        tid2 = i + 4
        middle_node = P.variable(name=f"middle_{i}")
        call1 = test("a", b=middle_node)
        call2 = test(middle_node)

        # Necessary to make DAG
        process.rewrite_call(call1)
        process.rewrite_call(call2)

        thread1 = Thread(tid=tid1, process=process, call=call1, context_id=0)
        call1.thread = thread1
        thread2 = Thread(tid=tid2, process=process, call=call2, context_id=0)
        call2.thread = thread2

        threads.append(thread1)
        threads.append(thread2)

    threads.sort(key=lambda x: x.tid)  # sort as A, A, A, A, B, B, B, B order

    for thread in threads:
        dispatcher.push_thread(thread)

    for _ in range(8):
        dispatched_threads = dispatcher.dispatch()
        assert len(dispatched_threads) == 1
        thread = dispatched_threads[0]
        thread.engine.remove_thread(thread)  # Free loc


@P.semantic_function()
def test_1000(
    b: P.Output(
        sampling_config=P.SamplingConfig(max_gen_length=1000),
    )
):
    """This is a function {{b}}"""


def test_token_capacity():
    dispatcher_config = DispatcherConfig(
        dag_aware=False,
        app_fifo=False,
        max_queue_size=1024,
    )

    # 4 identical engines
    tokenizer = Tokenizer()
    engine_config = EngineConfig(
        tokens_capacity=2048,
        tokenizer="hf-internal-testing/llama-tokenizer",
    )

    # 1 engine
    engines = {
        0: ExecutionEngine(engine_id=0, config=engine_config, tokenizer=tokenizer)
    }

    # init dispatcher
    dispatcher = ThreadDispatcher(config=dispatcher_config, engines=engines)
    mem_space = MemorySpace()
    process = Process(
        pid=0,
        dispatcher=dispatcher,
        tokenizer=tokenizer,
        memory_space=mem_space,
    )

    # 8 threads
    call = test_1000()
    process.rewrite_call(call)
    for i in range(8):
        thread = Thread(tid=i, process=process, call=call, context_id=0)
        dispatcher.push_thread(thread)

    dispatched_threads = dispatcher.dispatch()
    assert len(dispatched_threads) == 2

    engines[0].remove_thread(dispatched_threads[0])
    engines[0].remove_thread(dispatched_threads[1])

    dispatched_threads = dispatcher.dispatch()
    assert len(dispatched_threads) == 2


@P.semantic_function()
def test_prefix1(a: P.Input, b: P.Output):
    """Prefix1 {{a}} function {{b}}"""


@P.semantic_function()
def test_prefix2(a: P.Input, b: P.Output):
    """Prefix2 {{a}} function {{b}}"""


def test_ctx_aware():
    dispatcher_config = DispatcherConfig(
        dag_aware=False,
        app_fifo=False,
        max_queue_size=1024,
    )

    # 4 identical engines
    tokenizer = Tokenizer()
    engine_config = EngineConfig(tokenizer="hf-internal-testing/llama-tokenizer")

    # 2 engine
    engines = {
        0: ExecutionEngine(engine_id=0, config=engine_config, tokenizer=tokenizer),
        1: ExecutionEngine(engine_id=1, config=engine_config, tokenizer=tokenizer),
    }

    # init dispatcher
    mem_space = MemorySpace()
    dispatcher = ThreadDispatcher(
        config=dispatcher_config, engines=engines, memory_space=mem_space
    )
    process = Process(
        pid=0,
        dispatcher=dispatcher,
        tokenizer=tokenizer,
        memory_space=mem_space,
    )

    # cache prefix & pseudo context
    prefix1_ctx = Context(context_id=0, engine=engines[0])
    prefix2_ctx = Context(context_id=1, engine=engines[1])
    mem_space.prefix_cache[(test_prefix1.prefix.text, 0)] = prefix1_ctx
    mem_space.prefix_cache[(test_prefix2.prefix.text, 0)] = prefix2_ctx

    # 8 threads
    for i in range(8):
        call = test_prefix1("a") if i % 2 == 0 else test_prefix2("a")
        process.rewrite_call(call)
        thread = Thread(tid=i, process=process, call=call, context_id=0)
        dispatcher.push_thread(thread)

    dispatched_threads = dispatcher.dispatch()
    assert len(dispatched_threads) == 8


if __name__ == "__main__":
    # test_default_policy()
    # test_dag_aware_policy()
    # test_dispatcher_order()
    # test_app_fifo()
    # test_token_capacity()
    test_ctx_aware()
