# Copyright (c) 2023 by Microsoft Corporation.
# Licensed under the MIT license.

from dataclasses import dataclass
from typing import Union, Dict, Optional
from enum import Enum

from parrot.protocol.sampling_config import SamplingConfig
from parrot.exceptions import ParrotOSUserError


@dataclass
class RequestPlaceholder:
    """A placeholder in the request."""

    name: str
    is_output: bool
    var_id: Optional[str] = None
    const_value: Optional[str] = None
    sampling_config: Optional[Union[Dict, SamplingConfig]] = None

    def __post_init__(self):
        # Cast sampling_config to SamplingConfig.
        if self.sampling_config is not None:
            self.sampling_config = SamplingConfig(**self.sampling_config)

        # Check input/output arguments.
        if self.is_output:
            if self.const_value is not None:
                raise ParrotOSUserError(
                    ValueError("Output placeholder should not have const_value.")
                )
            if self.var_id is not None:
                raise ParrotOSUserError(
                    ValueError("Output placeholder should not have var_id.")
                )

            if self.sampling_config is None:
                self.sampling_config = SamplingConfig()
        else:
            if self.var_id is not None and self.const_value is not None:
                raise ParrotOSUserError(
                    ValueError(
                        "Input placeholder should not have both var_id and const_value.",
                    )
                )

    @property
    def should_create(self):
        """Return whether we should created a new SV for this placeholder."""

        return self.is_output or (self.var_id is None and self.const_value is None)
