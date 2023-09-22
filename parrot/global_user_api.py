import asyncio
import contextlib
import time

from .orchestration.controller import Controller
from .executor.executor import Executor
from .program.function import SemanticFunction
from .orchestration.tokenize import TokenizedStorage

# Initialize the global components

global_controller = Controller()
global_tokenized_storage = TokenizedStorage(global_controller)
global_executor = Executor(global_controller, global_tokenized_storage)

# Set the controller because we need to register
SemanticFunction._controller = global_controller


@contextlib.contextmanager
def controller_running_context(timeit: bool):
    """Under this context, the global controller is running."""

    # Set the executor
    SemanticFunction._executor = global_executor

    global_controller.run()
    global_controller.caching_function_prefix(global_tokenized_storage)

    if timeit:
        st = time.perf_counter_ns()

    try:
        yield
    except BaseException as e:
        # This is mainly used to catch the error in the `main`
        #
        # For errors in coroutines, we use the fail fast mode and quit the whole system
        # In this case, we can only see a SystemExit error
        print("Error happens when executing Parrot program: ", type(e), repr(e))
        # print("Traceback: ", traceback.format_exc())

    if timeit:
        ed = time.perf_counter_ns()
        print(f"[Timeit] E2E Program Execution Time: {(ed - st) / 1e9} (s).")

    global_controller.free_function_prefix()


def register_tokenizer(*args, **kwargs):
    global_controller.register_tokenizer(*args, **kwargs)


def register_engine(*args, **kwargs):
    global_controller.register_engine(*args, **kwargs)


def parrot_run_aysnc(coroutine, timeit: bool = False):
    with controller_running_context(timeit):
        # asyncio.run(coroutine)
        loop = asyncio.new_event_loop()
        loop.run_until_complete(coroutine)
        loop.close()
