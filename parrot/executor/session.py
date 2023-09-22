from typing import Optional, List
from queue import Queue

from .instructions import Instruction, ConstantFill, PlaceholderFill, Generation
from .tokens_holder import TokensHolder
from ..orchestration.context import Context
from ..orchestration.engine import ExecutionEngine
from ..program.function import Promise
from ..protocol import fill, generate, SamplingParams
from ..protocol import free_context
from ..utils import RecyclePool, get_logger, create_task_in_loop
from ..constants import RECYCLE_POOL_SIZE, STREAMING_END_TOKEN_ID, FILL_NO_CHUNK


logger = get_logger("Session")


async def detokenize_coroutine(holder: TokensHolder):
    assert holder.producer is not None, "Producer should be set."
    prev_last_token = None
    async for chunk in holder.producer.detokenize_pipe.generator():
        holder.sync_to_placeholder_partial(chunk, prev_last_token)
        prev_last_token = chunk[-1]
    holder.placeholder.ready_event.set()


class Session:
    """A session represents a running promise in the executor."""

    session_id_manager = RecyclePool(RECYCLE_POOL_SIZE)

    def __init__(self, promise: Promise, context: Context):
        # ---------- Basic info ----------
        self.session_id = Session.session_id_manager.allocate()
        self.promise = promise
        self.context = context

        # ---------- Attached engine ----------
        self.engine_name: Optional[str] = None
        self.engine: Optional[ExecutionEngine] = None

        # ---------- Instructions queue ----------
        self.instructions: Queue[Instruction] = Queue()

        # ---------- Fill tokens buffer ----------
        # This buffer is used to merge multiple Fill instructions into one Fill primitive.
        self._fill_tokens_buffer: List[int] = []

        # NOTE(chaofan): now we use a fixed sampling_params for all sessions
        self.sampling_params = SamplingParams(
            temperature=0.8,
            top_p=0.95,
            max_gen_length=512,  # 128,
        )

    def __del__(self):
        # print("Session deleted.")
        Session.session_id_manager.free(self.session_id)

        try:
            resp = free_context(
                self.engine.http_address,
                self.context.context_id,
            )
        except BaseException as e:
            logger.error(
                f"Context: {self.context.context_id} did not free correctly: {type(e)}, {e}."
            )
        else:
            logger.info(
                f"Context: {self.context.context_id} freed. Freed tokens: {resp.num_freed_tokens}"
            )

    async def _flush_fill_tokens_buffer(self):
        buffer_len = len(self._fill_tokens_buffer)
        if buffer_len == 0:
            return

        num_filled_tokens = 0
        chunk_size = self.engine.fill_chunk_size
        if chunk_size == FILL_NO_CHUNK:
            chunk_size = buffer_len

        for i in range(buffer_len // chunk_size):
            chunked_tokens = self._fill_tokens_buffer[
                i * chunk_size : (i + 1) * chunk_size
            ]

            logger.debug(
                f"Session {self.session_id} submit Fill primitive (size: {len(chunked_tokens)})"
            )

            resp = await fill(
                self.engine.http_address,
                session_id=self.session_id,
                token_ids=chunked_tokens,
                context_id=self.context.context_id,
                parent_context_id=self.context.parent_context_id,
            )
            num_filled_tokens += resp.num_filled_tokens
        assert (
            num_filled_tokens == buffer_len
        ), f"Not all tokens are filled. Filled: {num_filled_tokens}, total: {buffer_len}"
        self._fill_tokens_buffer = []

    async def execute_coroutine(self):
        while not self.instructions.empty():
            inst = self.instructions.get()

            if isinstance(inst, Generation):
                # Flush the buffer first.
                await self._flush_fill_tokens_buffer()

                logger.debug(
                    f"Session {self.session_id} submit Generation primitive (instruction: {inst})"
                )

                generator = generate(
                    self.engine.http_address,
                    session_id=self.session_id,
                    context_id=self.context.context_id,
                    parent_context_id=self.context.parent_context_id,
                    sampling_params=self.sampling_params,
                    # We don't fork new context. Hence parent_context_id=-1
                )

                assert not inst.output_holder.ready, "Output holder should be empty."
                inst.output_holder.token_ids = []

                create_task_in_loop(detokenize_coroutine(inst.output_holder))

                # Start streaming
                inst.output_holder.streaming_event.set()
                async for token_id in generator:
                    inst.output_holder.send_token(token_id, put_into_holder=True)
                inst.output_holder.send_token(
                    STREAMING_END_TOKEN_ID, put_into_holder=False
                )
                inst.output_holder.ready_event.set()
            elif isinstance(inst, ConstantFill):
                self._fill_tokens_buffer.extend(inst.token_ids)
            elif isinstance(inst, PlaceholderFill):
                # Lock unitl the input holder is streaming.
                # Then there are two cases:
                # 1. The input holder is ready. We can fill the whole data.
                # 2. The input holder is not ready. We can fill the data chunk by chunk.
                await inst.input_holder.streaming_event.wait()

                if inst.input_holder.ready:
                    # Has the whole data
                    # In this case, the placeholder must be synced.
                    self._fill_tokens_buffer.extend(inst.input_holder.token_ids)
                else:
                    # Not ready. Flush the buffer first.
                    await self._flush_fill_tokens_buffer()
                    # Streaming input. Pipeling filling.
                    num_filled_tokens = 0
                    async for chunk in inst.input_pipe.generator():
                        resp = await fill(
                            self.engine.http_address,
                            session_id=self.session_id,
                            token_ids=chunk,
                            context_id=self.context.context_id,
                            parent_context_id=self.context.parent_context_id,
                        )
                        num_filled_tokens += resp.num_filled_tokens
                    should_filled = len(inst.input_holder.token_ids)
                    assert (
                        num_filled_tokens == should_filled
                    ), f"Not all tokens are filled. Filled: {num_filled_tokens}, total: {should_filled}"
