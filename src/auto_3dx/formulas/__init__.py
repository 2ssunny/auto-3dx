"""High-level access to CATIA formulas and relations.

Exposes `Formula` (a single named relation) and `FormulaCollection` (a
Part's `Relations`), matching the verified COM surface documented in
`docs/conventions.md` section 1.2.1 and the public API contract in
section 6.12.
"""

from auto_3dx.formulas.collection import FormulaCollection
from auto_3dx.formulas.formula import Formula

__all__ = [
    "Formula",
    "FormulaCollection",
]
