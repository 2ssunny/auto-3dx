"""The model generation: one counter per Part that makes stale topology detectable.

Topology references are transient. A BRep name cannot be stored and resolved again,
a rebuild can change every edge and face name and index, and reusing an old
reference after a change succeeds or fails depending on whether that particular edge
survived -- which a caller cannot know. The SDK therefore counts model changes and
refuses a reference taken before the latest one (`docs/api-design.md` section 5).

The counter used to live inside `PartDesign`, and only its own create and remove
paths advanced it. Everything else that changes the model -- feature dimension
setters, pattern creation, sketches, planes, parameters, `Part.update()` -- went
untracked, although a single pad height change was measured rewriting a solid from
20 edges to 29 with every name changed (probe 31). One shared counter, owned by the
`Part` and handed to every collection and wrapper, is what closes that gap.

This module is deliberately a leaf: it imports only `errors`, so `geometry`,
`parameters`, `formulas` and `core` can all depend on it without a cycle.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from auto_3dx.errors import StaleSnapshotError


class ModelGeneration:
    """Counts the model changes made through the SDK for one Part.

    Obtain it from the owning `Part`; do not share one instance between Parts.
    Changes made outside the SDK, through the CATIA user interface or another
    script, are invisible to it.
    """

    def __init__(self) -> None:
        """Starts at generation zero."""
        self._value = 0

    @property
    def value(self) -> int:
        """int: The current generation."""
        return self._value

    def advance(self) -> None:
        """Marks every outstanding topology snapshot as describing an older model."""
        self._value += 1

    @contextmanager
    def mutation(self) -> Iterator[None]:
        """Advances the generation once the enclosed COM mutation has been attempted.

        The advance happens whether the block returns or raises. A mutating COM call
        that raised may still have changed the model: `AddNew*` can create a feature
        and then fail its rename, and a failed `Part.Update()` leaves the model in a
        state the caller must repair. Advancing on attempt rather than on success
        keeps both cases safe.

        Validation that happens before any COM call belongs outside this block, so a
        request rejected before reaching CATIA leaves the generation alone.

        Yields:
            Nothing. The block is the mutation.
        """
        try:
            yield
        finally:
            self.advance()

    def require_current(self, generation: int, what: str, retake: str) -> None:
        """Refuses a topology handle taken before the latest model change.

        Args:
            generation: The generation the handle's snapshot was taken at.
            what: What the handle is, for the message, such as ``"edge"``.
            retake: The call that produces a fresh snapshot, for the message,
                such as ``"part.topology.edges()"``.

        Raises:
            StaleSnapshotError: If `generation` is not the current generation.
                Raised before any COM call, so the model is untouched.
        """
        if generation != self._value:
            raise StaleSnapshotError(
                f"This {what} came from a snapshot of an older model "
                f"(generation {generation}, now {self._value}). CATIA would accept "
                "it sometimes and fail unpredictably at creation or at update. "
                f"Call {retake} again and pick the {what} from the new snapshot."
            )

    def __repr__(self) -> str:
        """str: Debug representation showing the current value."""
        return f"ModelGeneration(value={self._value})"
