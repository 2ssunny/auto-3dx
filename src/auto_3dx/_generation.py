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

A counter per `Part` *wrapper* was not enough either. `Catia.active_part()` builds a
new wrapper on every call, and so do `part_named()` and a second `Catia.attach()`, so
two wrappers of one model could each hold a counter the other never advanced. The
generation is therefore shared by the underlying CATIA Part: `shared_generation`
hands every wrapper of the same Part one counter, matched by COM identity. Two reads
of the active Part compare `==` while `is` differs, `part_named()` of the same name
compares `==`, and a different open Part compares unequal (live, 2026-09-15).

This module is deliberately a leaf: it imports only `errors`, so `geometry`,
`parameters`, `formulas` and `core` can all depend on it without a cycle.
"""

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pywintypes

from auto_3dx.errors import StaleSnapshotError


class ModelGeneration:
    """Counts the model changes made through the SDK for one CATIA Part.

    Obtain it through `shared_generation`, which `Part` does, so every wrapper of the
    same Part shares one instance. Never share one instance between different Parts.
    Changes made outside the SDK, through the CATIA user interface or another script,
    are invisible to it.
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


class _GenerationRegistry:
    """Maps each CATIA Part, by COM identity, to its one `ModelGeneration`.

    Entries are kept for the life of the process. Forgetting a Part would hand a
    later wrapper a fresh counter at zero, and a snapshot still held from the old
    counter at zero would then look current. A process touches few Parts, so a
    strong reference per Part costs little.
    """

    def __init__(self) -> None:
        """Starts with no known Parts."""
        self._entries: list[tuple[Any, ModelGeneration]] = []
        self._lock = threading.Lock()

    def generation_for(self, com_object: Any) -> ModelGeneration:
        """Returns the generation of this Part, creating it on first sight.

        Args:
            com_object: The raw CATIA `Part` COM object.

        Returns:
            The same `ModelGeneration` for every COM object that compares `==`.
        """
        with self._lock:
            for known, generation in self._entries:
                if _same_com_object(known, com_object):
                    return generation
            generation = ModelGeneration()
            self._entries.append((com_object, generation))
            return generation


def _same_com_object(known: Any, candidate: Any) -> bool:
    """Compares two COM objects by identity, treating a failed comparison as different.

    A comparison can fail, for example against a proxy whose object has gone away.
    Such an object cannot be the Part now being wrapped, and a spare counter is safe,
    whereas sharing a counter between two different Parts would not be.

    Args:
        known: A COM object already in the registry.
        candidate: The COM object being looked up.

    Returns:
        `True` only if the objects compare equal.
    """
    try:
        return bool(known == candidate)
    except (pywintypes.com_error, TypeError, AttributeError):
        return False


_REGISTRY = _GenerationRegistry()


def shared_generation(com_object: Any) -> ModelGeneration:
    """Returns the process-wide generation of a CATIA Part.

    Args:
        com_object: The raw CATIA `Part` COM object.

    Returns:
        One `ModelGeneration` per underlying Part, whichever wrapper, `Catia`
        instance or lookup produced the COM object.
    """
    return _REGISTRY.generation_for(com_object)
