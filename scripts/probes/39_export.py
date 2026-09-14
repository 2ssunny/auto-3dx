"""Probe whether ``part.export`` (docs/api-design.md section 12) can exist at all.

``docs/api-design.md`` section 12 reserves the name ``export`` for writing a Part
to a neutral file format (STEP, STL, ...), and says plainly: "It does not exist
yet." This probe gathers the live evidence that decides whether it ever can, and
if so, what the call shape is. Nothing here becomes public API by itself.

WHY THIS IS HARD (read before touching the code below):

3DEXPERIENCE is not CATIA V5. ``docs/conventions.md`` section 1 and
``docs/plm_object_creation.md`` establish, by live probing, that there are no
file-based ``Document`` objects reachable from a normal session:
``Application.ActiveDocument`` raises ``com_error`` in this installation, and
``Part.Parent`` is a ``VPMRepReference`` (a PLM object), not a ``Document``. The
V5 idiom ``Document.ExportData(path, "stp")`` cannot be assumed to exist or to
work just because it exists in the type library -- CATIA V5 and 3DEXPERIENCE
share type libraries but not always live object graphs.

Saving is a different safety class from exporting, and this probe never saves.
``PLMPropagateService.Save()`` and ``PLMPropagateService.PLMPropagate()`` commit
to the server and include every unsaved change in the *whole session*, not just
this probe's. Both are never called here, and nothing whose name or documented
behaviour suggests it saves, checks in, propagates, or synchronises with the
server is called either. ``PartDocument.Save()`` / ``PartDocument.SaveAs()``
(found in the type library alongside ``ExportData``, see below) are the same
kind of call and are excluded from every candidate list for that reason, not
because they were untested.

A call that did not throw is not evidence. ``docs/conventions.md`` section 1.4
records an inertia measurement that returned correct values in one session and
silently all zeros in another, on an unchanged model. So an export attempt here
is judged only by the file it produced: it exists, it is non-empty, and its
content is plausible for the claimed format. Every check prints PASS or FAIL
plus the file size; nothing is taken on faith from a call's return value alone.

WHAT WAS FOUND IN THE GENERATED TYPE LIBRARY
(``C:\\Users\\ssunn\\AppData\\Local\\Temp\\gen_py\\3.13``), grepped for members
named like Export, ExportData, DataExchange, STEP, Stp, STL, Iges, Translator,
Convert on every class, including ``Application``, ``Editor``, ``Part``,
``Document`` and every ``*Service`` class:

From ``14F197B2-0771-11D1-A5B1-00A0C9575177x0x0x0.py`` (InfInterfaces):

    class Documents(DispatchBaseClass):
        CLSID = IID('{7FBD9BE6-3CBE-0000-0280-030BA6000000}')
        def Add(self, docType): ...             # -> Document
        def Item(self, iIndex): ...             # -> Document
        def NewFrom(self, iFileName): ...       # -> Document
        def Open(self, iFileName): ...          # -> Document
        def Read(self, iFileName): ...          # -> Document
        # props: Application, Count, Name, Parent

    class Document(DispatchBaseClass):
        CLSID = IID('{7FBD9D5A-CFBA-0000-0280-030BA6000000}')
        def ExportData(self, fileName, format): ...   # -> void
        # also: Activate, Close, CreateFilter, CreateReferenceFromName, GetItem

    class Editor(DispatchBaseClass):
        def GetService(self, iService): ...     # -> Service   (used by probes 15, 30)
        # props: ActiveObject, Application, Name, Parent, Selection

From ``0D90A5C9-3B08-11D1-A26C-0000F87546FDx0x0x0.py`` (MechanicalModeler):

    class PartDocument(DispatchBaseClass):
        CLSID = IID('{818C8B33-806B-0000-0280-030D3B000000}')
        def Activate(self): ...
        def Save(self): ...                            # NEVER CALLED (persistence)
        def SaveAs(self, fileName): ...                 # NEVER CALLED (persistence)
        def ExportData(self, fileName, format): ...     # -> void
        def Close(self): ...
        # also: CreateFilter, CreateReferenceFromName, GetItem, GetWorkbench, ...

    class Part(DispatchBaseClass):
        # confirmed again, matches docs/conventions.md section 1 verbatim:
        # methods: Activate, CreateReferenceFromBRepName, CreateReferenceFromGeometry,
        #   CreateReferenceFromName, CreateReferenceFromObject, FindObjectByName,
        #   Freeze, GetCustomerFactory, GetItem, Inactivate, IsFrozen, IsInactive,
        #   IsUpToDate, Unfreeze, Update, UpdateObject
        # Part itself has NO Export-family member of any kind.

From ``31761CA0-8F61-4387-AED7-A5D1C2B8B957x0x0x0.py`` (VPM PLM object types):

    class VPMReference(DispatchBaseClass):      # Part.Parent.Parent-ish PLM object
        def GetAttributeValue(self, iAttrName): ...
        def GetCustomType(self): ...
        def SetAttributeValue(self, iAttrName, iAttrValue): ...
        # props: Application, Instances, Name, Parent, Publications, RepInstances
        # NO Export-family member.

    class VPMRepReference(DispatchBaseClass):   # Part.Parent in this installation
        def GetAttributeValue(self, iAttrName): ...
        def GetCustomType(self): ...
        def SetAttributeValue(self, iAttrName, iAttrValue): ...
        # props: Application, Father, Name, Parent, ParentRepInstances
        # NO Export-family member. Confirms docs/conventions.md: this chain is a
        # dead end for export, same as it was for face/edge references.

From ``34C26D90-38C0-443F-91DF-F38CA0E5DBFEx0x0x0.py``:

    class PLMDocumentServices(DispatchBaseClass):
        CLSID = IID('{3071B17B-5E62-4C19-AA0B-24B502311ACF}')
        def CreateDocument(self, iAttrNames, iAttrValues, iFilePathNames,
                            iFileComment): ...   # -> PLMDocument

    ``PLMDocumentServices`` is reachable via ``Editor.GetService`` (confirmed
    obtainable in ``docs/plm_object_creation.md`` section 2). Its
    ``CreateDocument`` takes ``iFilePathNames`` as an INPUT: it attaches an
    *existing* file to a *new* PLM document, the opposite direction from
    exporting the current Part to a fresh neutral file. Creating a PLM document
    is also itself a PLM-persisting side effect this probe must not risk as a
    side channel around the "never propagate/save" rule. Not attempted, in
    either mode, for both reasons.

MEMBERS LOOKED FOR AND NOT FOUND ANYWHERE ON ``Part``, ``Editor``, ``Application``,
or any obtainable service:

* No ``Export`` / ``ExportData`` / ``ExportTo`` member exists directly on the
  ``Part`` COM object returned by ``catia.active_part().com_object``.
* No service name resembling an export/translation/data-exchange service
  (``ExportService``, ``DataExchangeService``, ``STEPService``, ``STLService``,
  ``TranslatorService``, ``CATIAExportService``) is a real ``*Service`` class in
  the type library. The only genuine PLM/data services found by name anywhere
  are: ``PLMNewService``, ``PLMOpenService``, ``PLMPropagateService``,
  ``PLMProductService``, ``PLMRefreshService``, ``PLMScriptService``,
  ``ProductSessionService``, ``PLMDocumentServices``, ``PLMSearchService``,
  ``SystemService``, ``VPMSessionService``, ``DELPPRService``, plus the
  measurement trio ``InertiaService`` / ``InertiaBoxService`` /
  ``MeasurableService`` (docs/plm_object_creation.md, probe 30). None of these
  classes has an Export-family member.
* Every ``*Export*`` / ``*Translator*`` / ``*Convert*`` class elsewhere in the
  type library belongs to an unrelated discipline and does not apply to a
  generic Part: ``ManufacturingExport`` (NC toolpath data),
  ``ManufacturingResourceGeomOutput`` (manufacturing resource geometry),
  ``RscIOSignalsExchange`` (robotics I/O signal mappings), ``SimExportField`` /
  ``SimHistoryCurve`` / ``SimStressLine`` / ``SimManagerSIMExport`` (simulation
  results), ``Section.Export`` / ``ExportTo`` / ``ExportAsDrawing`` (2D section
  drawings), ``OlpTranslatorHelper`` (robot program text), ``Unit.ConvertToMKS``
  and ``SrsCoordinateConverter`` (unit/coordinate conversion, not file export).
  None of these classes is called here.

THE ONLY LIVE-PLAUSIBLE ROUTE: ``Application.Documents``. ``docs/plm_object_
creation.md`` section 1 records ``Application.Documents`` as existing, with
``Count == 2`` in that session, even though ``Application.ActiveDocument``
fails. This was never explored further. If any item in that collection is
COM-typed as ``Document`` or ``PartDocument`` (checked here with
``type(obj).__name__``, per docs/conventions.md section 4's identification
rule), it is the one path through which ``ExportData`` could be tried at all.
This probe enumerates ``Documents`` in BOTH modes (read-only, so safe as pure
discovery) and only attempts ``ExportData`` in ``--run`` mode, and only on an
item whose type name is exactly ``"Document"`` or ``"PartDocument"``.

WHAT THE PROBE ATTEMPTS, IN ORDER, UNDER ``--run --output-dir <dir>``:

1. Re-does the discovery pass (Documents enumeration) to find an export-capable
   document object. If none is found, it stops: no candidate is called blind.
2. For that object, for each format in ``EXPORT_FORMATS`` (STEP then STL, in
   that order -- STEP first because its ASCII header makes content-checking
   unambiguous), calls ``ExportData(path, format_code)`` where ``path`` is
   inside ``--output-dir`` with a fixed prefix and a random token, and the
   directory must already exist and the target must not already exist.
3. Checks the resulting file: exists, non-empty, and for STEP a leading
   ``ISO-10303-21;`` marker; for STL either an ASCII ``solid`` header or a
   binary header whose declared triangle count matches the file size via
   ``84 + 50 * count``.

Never calls ``Update()``, ``Save()``, or ``PLMPropagate()``; never creates,
renames, or removes any model feature; never changes ``Part.InWorkObject`` or
the CATIA selection. Prints "Document save: NOT CALLED" and
"PLMPropagate: NOT CALLED" at the end of every run.

Usage:

    python scripts/probes/39_export.py                          # discovery only
    python scripts/probes/39_export.py --run --output-dir OUTDIR # attempts export
"""

import argparse
import secrets
import struct
from pathlib import Path
from typing import Any, Callable, TypeVar

from auto_3dx import Catia

T = TypeVar("T")

FIRST_COM_INDEX = 1
MAX_DOCUMENTS = 20
MAX_TEXT_PREVIEW = 96

# Type names, from the type library quoted in the module docstring, that expose
# ExportData. Anything else found in Application.Documents is not a candidate.
EXPORTABLE_DOCUMENT_TYPES = ("Document", "PartDocument")

# CATIA's ExportData takes a bare format code as its second argument (V5
# convention; unverified here whether 3DEXPERIENCE's Document.ExportData
# accepts the same codes -- that is exactly what --run measures). STEP is
# tried before STL because its ASCII header makes a wrong-format write obvious
# immediately, before spending a second attempt on a format whose header check
# is more permissive.
FORMAT_STEP = "stp"
FORMAT_STL = "stl"
EXPORT_FORMATS = (FORMAT_STEP, FORMAT_STL)

OUTPUT_PREFIX = "auto3dx_probe39_export_"
RANDOM_TOKEN_BYTES = 4

STEP_MAGIC = b"ISO-10303-21;"
STL_ASCII_MAGIC = b"solid"
STL_BINARY_HEADER_SIZE = 80
STL_TRIANGLE_COUNT_FIELD_SIZE = 4
STL_BYTES_PER_TRIANGLE = 50

# Sentinel distinguishing "the action legitimately returned None/0/False" from
# "the action raised". Using None as the failure marker would conflate the two,
# the same convention probe 38 uses for the same reason.
_FAILED = object()


def _ascii(value: object) -> str:
    """Returns a console-safe rendering even on a legacy Windows code page."""
    return str(value).encode("ascii", "backslashreplace").decode("ascii")


def _short_text(value: object) -> str:
    """Returns a bounded, ASCII-safe representation for a possibly long value."""
    text = _ascii(value)
    if len(text) <= MAX_TEXT_PREVIEW:
        return text
    return f"{text[:MAX_TEXT_PREVIEW]}..."


def attempt(label: str, action: Callable[[], T]) -> Any:
    """Runs one COM action, reporting OK/FAILED, and never raising.

    Args:
        label: Short ASCII description printed with the result line.
        action: A zero-argument callable performing exactly one COM call.

    Returns:
        Whatever ``action`` returned, or the module-level ``_FAILED`` sentinel
        if it raised. Callers must check with ``is _FAILED`` rather than a
        truthiness test, because a legitimate result can be ``None`` or ``0``.
    """
    try:
        result = action()
    except Exception as error:  # noqa: BLE001 - this is a diagnostic probe
        print(f"FAILED {label}: {type(error).__name__}: {_short_text(error)}")
        return _FAILED
    print(f"OK     {label}")
    return result


def _print_omitted(total: int, shown: int) -> None:
    """Prints how many enumerated entries were left out of a bounded loop."""
    remaining = total - shown
    if remaining > 0:
        print(f"    ... {remaining} more omitted")


def find_export_candidates(application: Any) -> "list[tuple[int, Any, str]]":
    """Enumerates ``Application.Documents`` looking for an ExportData-typed item.

    This is read-only: it only reads ``Documents.Count`` and ``Item(i)`` and the
    COM type name of each item. It is run in both discovery and ``--run`` mode.

    Args:
        application: The raw ``Application`` COM object (``catia.com_object``).

    Returns:
        A list of ``(index, raw_document, type_name)`` for every item whose
        type name is in :data:`EXPORTABLE_DOCUMENT_TYPES`. Empty if
        ``Documents`` could not be read or no such item exists.
    """
    print("=== Application.Documents (the only route to ExportData found) ===")
    documents = attempt("Application.Documents", lambda: application.Documents)
    if documents is _FAILED:
        return []
    count = attempt("Documents.Count", lambda: int(documents.Count))
    if count is _FAILED:
        return []
    print(f"    Documents.Count = {count}")

    candidates: "list[tuple[int, Any, str]]" = []
    shown = min(count, MAX_DOCUMENTS)
    for index in range(FIRST_COM_INDEX, shown + FIRST_COM_INDEX):
        item = attempt(f"Documents.Item({index})", lambda index=index: documents.Item(index))
        if item is _FAILED:
            continue
        type_name = type(item).__name__
        name = attempt(f"Documents.Item({index}).Name", lambda item=item: _ascii(item.Name))
        name_text = "<unavailable>" if name is _FAILED else name
        print(f"    document[{index}] type={type_name} Name={name_text}")
        has_export_member = hasattr(item, "ExportData")
        print(f"    document[{index}] declares ExportData = {has_export_member}")
        if type_name in EXPORTABLE_DOCUMENT_TYPES:
            candidates.append((index, item, type_name))
    _print_omitted(count, shown)

    if not candidates:
        print(
            "    No item is typed Document/PartDocument: ExportData has no object "
            "to be called on in this session (matches docs/conventions.md: no "
            "file-based Document is reachable from Part.Parent either)."
        )
    return candidates


def check_step_file(path: Path) -> bool:
    """Checks a STEP file: exists, non-empty, and starts with the ISO header.

    Args:
        path: The file the export candidate claims to have written.

    Returns:
        True if every check passes.
    """
    if not path.is_file():
        print(f"    PASS exists: FAIL - {path} was not created")
        return False
    size = path.stat().st_size
    print(f"    PASS exists: file size = {size} bytes")
    if size == 0:
        print("    FAIL non-empty: file is empty")
        return False
    print("    PASS non-empty")
    header = path.read_bytes()[: len(STEP_MAGIC)]
    if header == STEP_MAGIC:
        print(f"    PASS content: starts with {STEP_MAGIC!r}")
        return True
    print(f"    FAIL content: expected {STEP_MAGIC!r}, got {header!r}")
    return False


def check_stl_file(path: Path) -> bool:
    """Checks an STL file: exists, non-empty, and a plausible ASCII or binary STL.

    An ASCII STL starts with ``solid``. A binary STL has an 80-byte header
    followed by a little-endian uint32 triangle count, and its total size must
    equal ``84 + 50 * count`` (4-byte count field + 50 bytes per triangle).

    Args:
        path: The file the export candidate claims to have written.

    Returns:
        True if every check passes.
    """
    if not path.is_file():
        print(f"    PASS exists: FAIL - {path} was not created")
        return False
    size = path.stat().st_size
    print(f"    PASS exists: file size = {size} bytes")
    if size == 0:
        print("    FAIL non-empty: file is empty")
        return False
    print("    PASS non-empty")

    data = path.read_bytes()
    if data[: len(STL_ASCII_MAGIC)] == STL_ASCII_MAGIC:
        print(f"    PASS content: ASCII STL, starts with {STL_ASCII_MAGIC!r}")
        return True

    header_end = STL_BINARY_HEADER_SIZE + STL_TRIANGLE_COUNT_FIELD_SIZE
    if size < header_end:
        print(f"    FAIL content: too short ({size} bytes) for a binary STL header")
        return False
    triangle_count = struct.unpack_from("<I", data, STL_BINARY_HEADER_SIZE)[0]
    expected_size = header_end + STL_BYTES_PER_TRIANGLE * triangle_count
    if expected_size == size:
        print(
            f"    PASS content: binary STL, {triangle_count} triangles, "
            f"size matches {header_end} + {STL_BYTES_PER_TRIANGLE} * count"
        )
        return True
    print(
        f"    FAIL content: binary STL header claims {triangle_count} triangles "
        f"(expects {expected_size} bytes) but file is {size} bytes"
    )
    return False


FORMAT_CHECKERS: "dict[str, Callable[[Path], bool]]" = {
    FORMAT_STEP: check_step_file,
    FORMAT_STL: check_stl_file,
}


def _random_token() -> str:
    """Returns a short random hex token for naming this run's output files."""
    return secrets.token_hex(RANDOM_TOKEN_BYTES)


def run_export_attempts(
    candidates: "list[tuple[int, Any, str]]", output_dir: Path
) -> None:
    """Attempts ExportData for each format on the first export candidate found.

    Refuses to run if ``output_dir`` does not already exist, and refuses to
    overwrite any existing target file (both checked before any COM call).

    Args:
        candidates: Result of :func:`find_export_candidates`.
        output_dir: Directory to write into; must already exist.
    """
    print("=== Export attempts ===")
    if not output_dir.is_dir():
        print(f"REFUSED: output directory does not exist: {output_dir}")
        print("Create it first; this probe will not create directories for you.")
        return
    if not candidates:
        print("No export-capable document object was found; nothing to attempt.")
        return

    index, document, type_name = candidates[0]
    print(f"Using document[{index}] (type={type_name}) as the ExportData target.")

    token = _random_token()
    for format_code in EXPORT_FORMATS:
        target = output_dir / f"{OUTPUT_PREFIX}{token}.{format_code}"
        print(f"--- format {format_code!r} -> {target} ---")
        if target.exists():
            print(f"    REFUSED: target already exists, will not overwrite: {target}")
            continue

        result = attempt(
            f"Document.ExportData({target!r}, {format_code!r})",
            lambda target=target, format_code=format_code: document.ExportData(
                str(target), format_code
            ),
        )
        if result is _FAILED:
            continue

        checker = FORMAT_CHECKERS[format_code]
        passed = checker(target)
        print(f"    overall: {'PASS' if passed else 'FAIL'}")
        print(f"    file left in place for inspection: {target}")


def parse_args() -> argparse.Namespace:
    """Parses command-line arguments.

    Returns:
        The parsed namespace with ``run`` (bool) and ``output_dir`` (Path | None).
    """
    parser = argparse.ArgumentParser(
        description=(
            "Probe whether a Part can be exported to a neutral file format "
            "(STEP, STL). Without --run, only discovers and reports candidate "
            "objects and members; writes nothing."
        )
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="Attempt each export candidate, writing files into --output-dir.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Existing directory to write probe output files into. Required with --run.",
    )
    return parser.parse_args()


def main() -> None:
    """Runs the discovery pass, and the export attempts if ``--run`` was given."""
    args = parse_args()
    if args.run and args.output_dir is None:
        raise SystemExit("--run requires --output-dir <existing directory>")

    catia = Catia.attach()
    application = catia.com_object
    editor = catia.active_editor()
    part = catia.active_part()

    print(f"Part: {_ascii(part.name)}")
    print(f"Mode: {'export attempt (--run)' if args.run else 'discovery only'}")
    print("Document save: NOT CALLED")
    print("PLMPropagate: NOT CALLED")

    print("=== Part COM object: direct Export-family member check ===")
    raw_part = part.com_object
    for member in ("Export", "ExportData", "ExportTo"):
        print(f"    Part.{member} present: {hasattr(raw_part, member)}")

    print("=== Part.Parent chain: direct Export-family member check ===")
    parent = attempt("Part.Parent", lambda: raw_part.Parent)
    if parent is not _FAILED and parent is not None:
        parent_type = type(parent).__name__
        print(f"    Part.Parent type = {parent_type}")
        for member in ("Export", "ExportData", "ExportTo"):
            print(f"    Part.Parent.{member} present: {hasattr(parent, member)}")

    print("=== Editor.GetService: export-shaped service name candidates ===")
    # Every *Service class actually confirmed reachable from GetService so far
    # (docs/plm_object_creation.md, probe 30) plus the export-shaped names a
    # caller might guess; none of these classes has an Export-family member
    # per the type library grep in the module docstring, so this section is
    # expected to find nothing -- it is here so a future release that adds one
    # is caught automatically instead of by memory.
    service_candidates = (
        "PLMDocumentServices",
        "ExportService",
        "DataExchangeService",
        "STEPService",
        "STLService",
        "TranslatorService",
        "CATIAExportService",
    )
    for name in service_candidates:
        service = attempt(f"Editor.GetService({name!r})", lambda n=name: editor.GetService(n))
        if service is _FAILED or service is None:
            continue
        for member in ("Export", "ExportData", "ExportTo", "CreateDocument"):
            print(f"    {name}.{member} present: {hasattr(service, member)}")

    candidates = find_export_candidates(application)

    if args.run:
        run_export_attempts(candidates, args.output_dir)
    else:
        print(
            "Discovery only: pass --run --output-dir <existing directory> to "
            "attempt ExportData on any candidate found above."
        )

    print("Document save: NOT CALLED")
    print("PLMPropagate: NOT CALLED")


if __name__ == "__main__":
    main()
