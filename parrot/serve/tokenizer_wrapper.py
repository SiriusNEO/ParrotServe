# Copyright (c) 2023 by Microsoft Corporation.
# Licensed under the MIT license.


from typing import Dict, List, Union
from transformers import AutoTokenizer, PreTrainedTokenizer, PreTrainedTokenizerFast

from parrot.exceptions import parrot_assert


HFTokenizer = Union[PreTrainedTokenizer, PreTrainedTokenizerFast]


class TokenizersWrapper:
    """TokenizersWrapper wraps a unified interface to tokenize/detokenize text.

    Different engines in OS may use different tokenizers, which are stored as a
    dictionary in this manager.
    """

    def __init__(self):
        # Map from tokenizer name to tokenizer object
        self._tokenizers: Dict[str, HFTokenizer] = {}

        # Map from tokenizer name to reference count
        self._tokenizer_ref_counter: Dict[str, int] = {}

    def register_tokenizer(self, tokenizer_name: str):
        """Register a new tokenizer in the server."""

        if tokenizer_name not in self._tokenizers:
            self._tokenizers[tokenizer_name] = AutoTokenizer.from_pretrained(
                tokenizer_name
            )

            self._tokenizer_ref_counter[tokenizer_name] = 0

        self._tokenizer_ref_counter[tokenizer_name] += 1

    def remove_tokenizer(self, tokenizer_name: str):
        """Remove a tokenizer from the server."""

        parrot_assert(
            tokenizer_name in self._tokenizers,
            f"Tokenizer {tokenizer_name} does not exist.",
        )

        self._tokenizer_ref_counter[tokenizer_name] -= 1

        if self._tokenizer_ref_counter[tokenizer_name] == 0:
            self._tokenizers.pop(tokenizer_name)
            self._tokenizer_ref_counter.pop(tokenizer_name)

    def get_tokenizer(self, tokenizer_name: str):
        parrot_assert(
            tokenizer_name in self._tokenizers,
            f"Tokenizer {tokenizer_name} does not exist.",
        )

        return self._tokenizers[tokenizer_name]

    # NOTE(chaofan): Ignore special tokens because we chunk the inputs.

    def tokenize(self, text: str, tokenizer_name: str) -> List[int]:
        """Tokenize a text using a specific tokenizer."""

        tokenizer = self.get_tokenizer(tokenizer_name)
        return tokenizer.encode(text, add_special_tokens=False)

    def tokenize_all(self, text: str) -> Dict[str, List[int]]:
        """Tokenize a text using all tokenizers.

        Returns:
            A dictionary from tokenizer name to token ids.
        """

        result = {}
        for tokenizer_name in self._tokenizers:
            result[tokenizer_name] = self.tokenize(text, tokenizer_name)

    def detokenize(
        self,
        token_ids: List[int],
        tokenizer_name: str,
    ) -> str:
        tokenizer = self.get_tokenizer(tokenizer_name)
        return tokenizer.decode(
            token_ids,
            skip_special_tokens=True,
            spaces_between_special_tokens=False,
            clean_up_tokenization_spaces=False,
        )
