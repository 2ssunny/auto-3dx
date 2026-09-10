# auto-3dx Module & API Conventions

이 문서는 `auto-3dx` 라이브러리 코드를 작성할 때 따르는 규칙과, 첫 번째 수직 기능
("실행 중인 Part의 기존 Length Parameter 수정 + update")의 확정된 공개 API contract를 정의한다.

여러 작업자가 병렬로 구현하더라도 이 문서의 signature를 그대로 구현하면 서로 맞물린다.

---

## 1. 검증된 사실 (Ground truth)

추측 금지. 아래는 B428_Cloud 설치본에서 실제 COM 호출로 확인한 내용이다.
이 목록에 없는 동작은 **미검증**이며, 구현 대상이 아니다.

### 환경

```text
Conda env      : auto-3dx
Python         : 3.11.16 (64-bit)
pywin32        : 312
Release        : B428_Cloud
com3dx.py      : <code>\python3dx\lib\com3dx.py
```

### COM 객체 계층 (실측)

```text
Application (CLSID {7D2C8116-DC44-0000-0280-030BA6000000})
  .ActiveEditor            -> Editor
      .ActiveObject        -> Part          (Part context)
                           -> VPMRootOccurrence (Assembly context)
      .Name, .Selection, .Application, .Parent
  .Name == "3DEXPERIENCE"
```

### `Part` (실측 property/method)

```text
readable : AnnotationSets, Application, AxisSystems, Bodies, Constraints, Density,
           GeometricElements, HybridBodies, HybridShapeFactory, InWorkObject,
           MainBody, Name, OrderedGeometricalSets, OriginElements, Parameters,
           Parent, Relations, ShapeFactory, UserSurfaces
methods  : Activate, CreateReferenceFromBRepName, CreateReferenceFromGeometry,
           CreateReferenceFromName, CreateReferenceFromObject, FindObjectByName,
           Freeze, GetCustomerFactory, GetItem, Inactivate, IsFrozen, IsInactive,
           IsUpToDate, Unfreeze, Update, UpdateObject
```

### `Part.Parameters` (실측)

```text
type     : Parameters
readable : Application, Count, Name, Parent, RootParameterSet, Units
methods  : CreateBoolean, CreateDimension, CreateInteger, CreateList, CreateReal,
           CreateSetOfParameters, CreateString, GetItem, GetNameToUseInRelation,
           Item, Remove, SubList
indexing : Item(1..Count)  -- 1-based. Item(name: str) 도 동작.
```

### `Length` parameter (실측)

```text
wrapper type    : Length            (type(obj).__name__ 로 식별)
readable        : Name, Value, ...
writable        : Value
Value python type: float
UI 대응          : Value == 150.0  <->  CATIA UI 표시 150mm
```

### 검증된 동작

| 동작 | 상태 |
|---|---|
| `attach_running_application()` | 검증 완료 |
| `ActiveEditor` / `ActiveObject` 조회 | 검증 완료 |
| Part / Assembly context 구분 | 검증 완료 |
| `Parameters.Count`, `Item(i)`, `Item(name)` | 검증 완료 |
| `Length.Value` 읽기 / 쓰기 | 검증 완료 |
| `Part.Update()` | 검증 완료 |
| Parameter 생성 (`CreateDimension` 등) | **미검증 — 구현 금지** |
| Formula / Relations | **미검증 — 구현 금지** |
| Sketch / Pad / GSD | **미검증 — 구현 금지** |
| 새 Part 생성 | **미검증 — 구현 금지** |
| Save / PLM propagate | **미검증 — 호출 금지** |

> **Save는 어떤 코드 경로에서도 호출하지 않는다.** 이 규칙에는 예외가 없다.

---

## 2. 코드 스타일

전역 규칙(`global-instructions/code_style.md`)을 따른다. 요약:

- `snake_case` 함수/변수, `PascalCase` 클래스
- **모든 함수 signature에 type hint 필수**
- **모든 public 함수/클래스에 Google style docstring 필수**
- import 순서: stdlib → third-party → local, 각 그룹 사이 빈 줄
- 매직 넘버/매직 스트링 금지 → 모듈 상수로 정의
- 최대 줄 길이 100자
- 들여쓰기 4칸
- dead code 금지 (사용하지 않는 import 남기지 않는다)

추가 규칙:

- 대상 Python은 **3.11+**. `Path | None` 같은 PEP 604 union을 그대로 쓴다.
  `from __future__ import annotations`는 사용하지 않는다.
- 주석은 *왜*를 설명한다. *무엇*은 코드가 말하게 한다.
- 모듈 비공개 헬퍼는 `_` prefix.

---

## 3. 계층과 의존 방향

```text
auto_3dx (public API)
        ↓
parameters
        ↓
core
        ↓
transport
        ↓
com3dx / pywin32 / Windows COM
```

- **역방향 import 금지.** `transport`는 `core`를 모른다. `core`는 `parameters`를 알지만
  `parameters`는 `core`를 모른다.
- `errors`는 모든 계층이 import할 수 있다 (leaf 모듈).

---

## 4. raw COM 격리 규칙

1. 모든 wrapper는 raw COM 객체를 `self._com_object`에 보관한다.
2. 읽기 전용 접근자 `com_object` property로 노출한다 (탈출구 겸 테스트용).
3. 공개 API는 `_oleobj_`, `CLSID`, `_prop_map_get_` 같은 COM 내부에 의존하지 않는다.
4. COM 객체의 **타입 식별은 `type(obj).__name__`** 으로 한다.
   (`com3dx`가 generated wrapper로 cast해 주므로 `"Part"`, `"Length"` 등이 나온다.)
5. `pywintypes.com_error`는 **`transport`, `core`, `parameters` 경계에서 전부 잡아
   `Auto3dxError` 계열로 변환**한다. 라이브러리 밖으로 `com_error`가 새어나가면 안 된다.

---

## 5. 예외 계층과 변환 규칙

```text
Auto3dxError
├── Com3dxNotFoundError      com3dx.py 헬퍼를 찾지 못함
├── CatiaConnectionError     세션 attach 실패 / 헬퍼 로딩 실패
├── NoActiveEditorError      ActiveEditor 없음
├── NoActivePartError        현재 편집 대상이 Part가 아님
├── ParameterNotFoundError   이름으로 parameter를 찾지 못함
├── ParameterTypeError       지원하지 않는 parameter 타입 / 값 타입
├── UnsupportedUnitError     지원하지 않는 단위
└── PartUpdateError          Part.Update() 실패
```

변환 규칙:

| 상황 | 발생시킬 예외 |
|---|---|
| `com3dx.py` 경로 탐색 실패 | `Com3dxNotFoundError` |
| 명시적/환경변수 경로가 실재하지 않음 | `Com3dxNotFoundError` (fallback 하지 않음) |
| `com3dx` 로딩/exec 실패 | `CatiaConnectionError` |
| 프로세스에 다른 릴리스의 `com3dx`가 이미 로딩됨 | `CatiaConnectionError` |
| `get3dxClient()`가 예외를 던짐 (`com_error` 포함) | `CatiaConnectionError` |
| `get3dxClient()`가 `None` 반환 | `CatiaConnectionError` |
| `ActiveEditor` 접근 실패 또는 `None` | `NoActiveEditorError` |
| `ActiveObject`가 `None` | `NoActivePartError` |
| `ActiveObject`가 `Part`가 아님 | `NoActivePartError` (실제 타입명을 메시지에 포함) |
| `Parameters.Item(name)` 실패 | `ParameterNotFoundError` |
| parameter 종류가 `Length`가 아님 | `ParameterTypeError` |
| 값이 `int`/`float`이 아님 (`bool` 포함 거부) | `ParameterTypeError` |
| 단위가 `"mm"`이 아님 | `UnsupportedUnitError` |
| `Part.Update()` 실패 | `PartUpdateError` |
| 위에 해당하지 않는 예상 밖 COM 실패 | `Auto3dxError` (HRESULT를 메시지에 포함) |

추가 규칙:

- 원인 예외는 항상 `raise ... from error`로 chain한다.
- 예외 메시지는 **영어**, 마침표로 끝낸다. 사용자가 취할 수 있는 행동을 포함하면 좋다.
- 메시지에 사실이 아닌 안내를 넣지 않는다.
  (예: attach 실패에 "open an editor"는 틀렸다. attach는 editor를 요구하지 않는다.)

---

## 6. 확정 공개 API contract

아래 signature는 **그대로** 구현한다. 임의로 이름이나 인자를 바꾸지 않는다.

### 6.1 `auto_3dx/errors.py`

```python
class Auto3dxError(Exception): ...
class Com3dxNotFoundError(Auto3dxError): ...
class CatiaConnectionError(Auto3dxError): ...
class NoActiveEditorError(Auto3dxError): ...
class NoActivePartError(Auto3dxError): ...
class ParameterNotFoundError(Auto3dxError): ...
class ParameterTypeError(Auto3dxError): ...
class UnsupportedUnitError(Auto3dxError): ...
class PartUpdateError(Auto3dxError): ...
```

### 6.2 `auto_3dx/transport/windows_com.py`

```python
COM3DX_PATH_ENV_VAR: str = "AUTO_3DX_COM3DX_PATH"

def find_com3dx_path(explicit_path: Path | None = None) -> Path: ...
def load_com3dx(path: Path) -> ModuleType: ...
def attach_running_application(com3dx_path: Path | None = None) -> Any: ...
```

### 6.3 `auto_3dx/core/application.py`

```python
class Catia:
    def __init__(self, com_object: Any) -> None: ...

    @classmethod
    def attach(cls, com3dx_path: Path | None = None) -> "Catia": ...

    @property
    def com_object(self) -> Any: ...

    @property
    def name(self) -> str: ...

    def active_editor(self) -> Any: ...      # raw Editor COM object
    def active_part(self) -> "Part": ...
```

### 6.4 `auto_3dx/core/part.py`

```python
class Part:
    def __init__(self, com_object: Any) -> None: ...

    @property
    def com_object(self) -> Any: ...

    @property
    def name(self) -> str: ...

    @property
    def parameters(self) -> "ParameterCollection": ...   # 최초 접근 시 생성 후 캐시

    def update(self) -> None: ...            # 실패 시 PartUpdateError. save 호출 금지.
```

### 6.5 `auto_3dx/parameters/parameter.py`

```python
LENGTH_KIND: str = "Length"
MILLIMETRE: str = "mm"
SUPPORTED_LENGTH_UNITS: frozenset[str] = frozenset({MILLIMETRE})

@dataclasses.dataclass(frozen=True)
class ParameterInfo:
    name: str
    kind: str
    value: Any
    unit: str | None

class Parameter:
    def __init__(self, com_object: Any) -> None: ...

    @property
    def com_object(self) -> Any: ...

    @property
    def name(self) -> str: ...

    @property
    def kind(self) -> str: ...               # type(com_object).__name__

    @property
    def value(self) -> Any: ...

    @property
    def unit(self) -> str | None: ...        # Length -> "mm", 그 외 -> None

    def set(self, value: float, unit: str = MILLIMETRE) -> None: ...

    def info(self) -> ParameterInfo: ...

    def __repr__(self) -> str: ...
```

`set()` 정책 (검증 범위로 제한):

```text
kind != "Length"              -> ParameterTypeError
unit not in SUPPORTED_UNITS   -> UnsupportedUnitError
type(value) is bool           -> ParameterTypeError   (bool은 int의 서브클래스이므로 명시적으로 거부)
not isinstance(value, (int, float)) -> ParameterTypeError
정상                           -> com_object.Value = float(value)
```

검사 순서는 위 표 순서를 지킨다. `set()`은 **`Part.Update()`를 호출하지 않는다.**

### 6.6 `auto_3dx/parameters/collection.py`

```python
class ParameterCollection:
    def __init__(self, com_object: Any) -> None: ...   # raw CATIA Parameters

    @property
    def com_object(self) -> Any: ...

    @property
    def count(self) -> int: ...

    def list(self) -> list[Parameter]: ...
    def names(self) -> list[str]: ...
    def get(self, name: str) -> Parameter: ...
    def set(self, name: str, value: float, unit: str = MILLIMETRE) -> None: ...

    def __len__(self) -> int: ...
    def __iter__(self) -> Iterator[Parameter]: ...
    def __contains__(self, name: object) -> bool: ...
    def __repr__(self) -> str: ...
```

구현 주의: 클래스 본문에서 `def list(...)`가 평가된 뒤에는 이름 `list`가 그 메서드로 바인딩된다.
따라서 그 아래에 오는 `def names(self) -> list[str]` 의 애노테이션은 빌트인 `list`가 아니라 방금
정의한 메서드를 참조해 `TypeError: 'function' object is not subscriptable`로 죽는다.
해당 애노테이션만 문자열(`-> "list[str]"`)로 쓴다. `py_compile`로는 잡히지 않으므로 실제 import로
확인해야 한다.

동작:

```text
count      -> com_object.Count
list()     -> [Parameter(com_object.Item(i)) for i in 1..Count]   # 1-based
names()    -> [p.name for p in list()]
get(name)  -> Parameter(com_object.Item(name)); 실패 시 ParameterNotFoundError
set(...)   -> get(name).set(value, unit)      # update는 호출하지 않는다
__contains__ -> get()이 성공하면 True, ParameterNotFoundError면 False
```

### 6.7 `auto_3dx/__init__.py`

```python
__all__ = [
    "Catia",
    "Part",
    "Parameter",
    "ParameterCollection",
    "ParameterInfo",
    "Auto3dxError",
    "CatiaConnectionError",
    "Com3dxNotFoundError",
    "NoActiveEditorError",
    "NoActivePartError",
    "ParameterNotFoundError",
    "ParameterTypeError",
    "PartUpdateError",
    "UnsupportedUnitError",
]
```

### 6.8 목표 사용 예

```python
from auto_3dx import Catia

catia = Catia.attach()
part = catia.active_part()

for parameter in part.parameters.list():
    print(parameter.name, parameter.kind, parameter.value)

part.parameters.set("AUTO3DX_TEST_LENGTH", 150, unit="mm")
part.update()
```

---

## 7. 테스트 컨벤션

- 프레임워크: `pytest`
- `tests/unit/` — **CATIA 없이 동작해야 한다.** COM 객체는 fake로 대체한다.
  `kind`는 `type(obj).__name__`으로 판별하므로, 클래스 이름을 `Length`로 만든 fake면 충분하다.
- `tests/integration/` — 실행 중인 3DEXPERIENCE 필요. `@pytest.mark.integration` 마커를 붙이고,
  기본 실행에서 제외한다. 세션이 없으면 `pytest.skip`.
- 통합 smoke test는 **원래 값을 `finally`에서 복원**한다. save는 호출하지 않는다.
- 테스트 이름: `test_<대상>_<조건>_<기대결과>`

---

## 8. 패키징

```text
Distribution name : auto-3dx
Import name       : auto_3dx
Layout            : src layout
requires-python   : >=3.11
dependencies      : pywin32
```

설치:

```powershell
conda activate auto-3dx
python -m pip install -e .
```

---

## 9. 불확실할 때

이 문서의 "검증된 사실"에 없는 COM 동작이 필요해지면:

1. 추측해서 구현하지 않는다.
2. `DSYAutomation.chm` / type library에서 확인한다.
3. 그래도 불확실하면 **작업을 멈추고 보고한다.** 미검증 경로를 조용히 넣지 않는다.
