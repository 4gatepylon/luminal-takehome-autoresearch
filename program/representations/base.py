"""Minimal contract for text representations of programs."""

from abc import ABC, abstractmethod

from program.core import Program


class Representation(ABC):
    """Encode without mutating the input; decode into a validated program.

    Implementations return text and leave file I/O to callers. Visualization-
    only representations implement decode by raising NotImplementedError.
    """

    @abstractmethod
    def encode(self, program: Program) -> str:
        """Validate and represent a program as text."""

    @abstractmethod
    def decode(self, text: str) -> Program:
        """Parse text, or raise NotImplementedError if decoding is unsupported."""
