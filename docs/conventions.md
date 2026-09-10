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
| Length parameter 생성 / ensure / remove | 검증 완료 (아래 1.1) |
| 그 외 Parameter 생성 (`CreateReal` 등) | **미검증 — 구현 금지** |
| Formula / Relations | **미검증 — 구현 금지** |
| Sketch / Pad / GSD | **미검증 — 구현 금지** |
| 새 Part 생성 | **미검증 — 구현 금지** |
| Save / PLM propagate | **미검증 — 호출 금지** |

> **Save는 어떤 코드 경로에서도 호출하지 않는다.** 이 규칙에는 예외가 없다.

### 1.1 Parameter 생성 (실측, `scripts/probes/11_create_dimension.py`)

type library가 고정한 signature:

```text
CreateDimension(iName: BSTR, iMagnitude: BSTR, iValue: double) -> Dimension
CreateReal(iName: BSTR, iValue: double)                        -> RealParam
```

`iMagnitude`는 `Parameters.Units` 컬렉션의 `Magnitude` 값이다. 이 설치본은 **대문자가
아니라 첫 글자만 대문자인 이름**을 쓴다. `"LENGTH"`가 아니라 `"Length"`다.

```text
Units.Count == 1887
Unit 항목: Name='Millimeter', Magnitude='Length', Symbol='mm'
Magnitude 예: Length, Angle, Time, Mass, Volume, Velocity, ...
```

`CreateDimension(name, "Length", v)`가 돌려주는 wrapper 타입은 `Dimension`이 아니라
파생 타입 **`Length`** 다 (`com3dx`의 `Dispatch3dx`가 파생 타입으로 cast해 준다).

**이름이 생성 경로에 따라 다르다.**

```text
CreateDimension("Span", ...) 로 만든 것 -> Name == "3D Shape00422533\Span"   (정규화)
CATIA UI f(x) 로 만든 것                -> Name == "AUTO3DX_TEST_LENGTH"      (짧은 이름)
조회는 짧은 이름과 정규화 이름 둘 다 동작한다.
```

그래서 `Parameter.name`은 CATIA가 준 값을 그대로 두고, `short_name`이 마지막
`\` 뒤만 돌려준다. 파라미터 셋을 쓰면 짧은 이름은 유일하지 않으므로 `name`이 정본이다.

**반드시 막아야 하는 CATIA 동작 3가지** (모두 실측):

| 입력 | CATIA 동작 | 라이브러리 대응 |
|---|---|---|
| 이미 있는 이름 | **조용히 수락**, 같은 이름의 파라미터가 2개 생김 | 사전 존재 검사 후 `ParameterAlreadyExistsError` |
| 빈 이름 | 수락 후 `Length.3`으로 자동 명명 | `ParameterNameError` |
| 이름에 `\` 포함 | 수락, `A\B`가 되어 정규화 이름과 구분 불가 | `ParameterNameError` |

중복 이름 가드는 **COM 호출 전에** 동작해야 한다. 도달하는 것 자체가 버그다.

`Parameters.Remove(name)`는 정규화 이름으로 동작하고, 제거 후 `Count`가 정상적으로
줄어든다. `Part.Update()`도 제거 후 성공한다.

### 1.2 Sketch와 Pad (실측, `scripts/probes/12_sketch_and_pad.py`, `13_sketch_identity.py`)

type library가 고정한 signature:

```text
OriginElements.PlaneXY / PlaneYZ / PlaneZX   -> Plane
Body.Sketches.Add(iPlane)                    -> Sketch
Sketch.OpenEdition()                         -> Factory2D
Sketch.CloseEdition()                        -> void
Factory2D.CreateLine(iX1, iY1, iX2, iY2)     -> Line2D
Factory2D.CreateClosedCircle(iCx, iCy, iR)   -> Circle2D
Factory2D.CreatePoint(iX, iY)                -> Point2D
ShapeFactory.AddNewPad(iSketch, iHeight)     -> Pad
```

검증된 흐름:

```text
PlaneXY -> Sketches.Add -> OpenEdition -> CreateLine x4 (닫힌 사각형)
  -> CloseEdition -> Part.Update() -> AddNewPad(sketch, 20) -> Part.Update()
```

Sketch 좌표와 Pad 높이는 **mm**다. 제약(Constraint) 없는 사각형 프로파일도 pad된다.

**평면은 타입으로 식별할 수 없다.** `OriginElements.PlaneXY`의 wrapper 타입은 `Plane`이
아니라 `AnyObject`이고 `Name`은 `"xy plane"`이다. 반드시 `OriginElements`의 속성으로
접근한다.

`Sketch`가 읽을 수 있는 것:

```text
AbsoluteAxis, Constraints, Factory2D, GeometricElements, Name, Parent
GetAbsoluteAxisData(oAxisData) -> 9 doubles
쓰기 가능: Name, CenterLine
```

**`Sketch`에는 support/plane 속성이 없다.** 어느 평면에 붙었는지는
`GetAbsoluteAxisData`로만 알 수 있고, 실측값은 support마다 다음과 같이 구분된다
(origin 3 + X방향 3 + Y방향 3):

```text
XY -> (0,0,0,  1,0,0,  0,1,0)
YZ -> (0,0,0,  0,1,0,  0,0,1)
ZX -> (0,0,0,  0,0,1,  1,0,0)
```

`Pad`가 읽을 수 있는 것:

```text
Name, Sketch, FirstLimit, SecondLimit, IsSymmetric, IsThin, MergeEnd,
NeutralFiber, DirectionType, DirectionOrientation
FirstLimit.Dimension.Value == AddNewPad에 넘긴 높이   (실측 15.0)
```

**형상 삭제는 `Editor.Selection`으로만 된다.** type library와 라이브 세션 양쪽에서 확인:

```text
Sketches methods : Add, GetBoundary, GetItem, Item        <- Remove 없음
Shapes   methods : GetBoundary, GetItem, Item             <- Remove 없음, Add도 없음
Selection methods: Add, Clear, Delete, Copy, Cut, Paste, Search, ...
Part.Parent      : VPMRepReference                        <- Selection 없음
```

`Parameters.Remove(name)`가 있다고 해서 `Shapes.Remove`도 있으리라 유추하면 안 된다.
실제로 호출하면 `AttributeError`다. 삭제 순서는 다음과 같다.

```text
Selection.Clear() -> Selection.Add(com_object) -> Selection.Delete() -> Selection.Clear()
```

마지막 `Clear()`를 빠뜨리면 지운 객체가 선택된 채 남아 다음 삭제 범위가 넓어진다.

이 때문에 삭제는 Part가 아니라 **editor의 기능**이다. `SketchCollection`과 `PartDesign`은
생성자에서 `selection`을 받고, `Catia.active_part()`가 `editor.Selection`을 넣어 준다.
`selection` 없이 만든 객체도 읽기·생성·update는 전부 되고 삭제만 막힌다.

**Pad를 지우면 그 Sketch까지 연쇄 삭제된다**(실측: Shapes 1->0, Sketches 1->0). 그래서 Pad를
먼저 지운 뒤 Sketch 삭제가 실패하는 것은 정상이다.

쓰기 가능 속성 (실측):

```text
Sketch : Name, CenterLine
Pad    : Name, DirectionOrientation, DirectionType, IsSymmetric, IsThin,
         MergeEnd, NeutralFiber
```

추가 실측 (`scripts/probes/14_identity_and_duplicates.py`):

**이름은 유일하지 않다.** `Sketch.Name`이 쓰기 가능하므로 두 스케치에 같은 이름을 줄 수 있고,
CATIA는 이를 거부하지 않는다.

```text
sketches: ['AUTO3DX_DUP_SKETCH', 'AUTO3DX_DUP_SKETCH']   <- 둘 다 수락됨
Sketches.Item('AUTO3DX_DUP_SKETCH') -> 둘 중 하나만 반환
```

따라서 이름 조회만으로 형상을 재사용하면 엉뚱한 프로파일을 잡을 수 있다. 이름으로 찾을 때는
**전체를 열거해 일치 개수를 세고, 2개 이상이면 거부**해야 한다.

**COM 객체 동일성 비교는 동작한다.**

```text
같은 객체를 두 번 가져와 비교  : a == b  -> True   (a is b는 False)
서로 다른 객체                 : a == b  -> False
pad.Sketch == 원본 sketch      : True
```

`is`는 쓰면 안 되고 `==`를 쓴다. wrapper는 매번 새로 생성되지만 `==`는 아래의 `_oleobj_`
동일성으로 내려간다. 이름 비교보다 이쪽이 정본이다.

**컬렉션 프로토콜 (실측 확인).** 모두 1-based `Item(i)` + `Count`.

```text
Sketches.Count / Item(i)            OK
Shapes.Count / Item(i)              OK   (Item(i).Name 읽기 가능)
GeometricElements.Count / Item(i)   OK   (Item(1).Name == 'AbsoluteAxis')
```

### 1.3 `ensure_*` 정책 (형상)

이름만 같다고 형상을 재사용하면 안 된다. 아래 비교는 모두 실측으로 읽을 수 있는 값이다.

```text
ensure_sketch(name, support)
  이름 2개 이상                      -> AmbiguousNameError   (먼저 검사)
  이름 없음                          -> 생성
  이름 있음 + 축 데이터 일치          -> 기존 재사용
  이름 있음 + 축 데이터 불일치        -> SketchSupportMismatchError

ensure_pad(name, sketch, height)
  이름 2개 이상                      -> AmbiguousNameError   (먼저 검사)
  이름 없음                          -> 생성
  이름 있음 + 같은 Sketch + 높이 같음 -> 그대로 재사용
  이름 있음 + 같은 Sketch + 높이 다름 -> FirstLimit.Dimension.Value 갱신
  이름 있음 + 다른 Sketch            -> FeatureConflictError
```

"같은 Sketch"는 **COM 동일성(`==`)** 으로 판정한다. 이름 비교는 위조 가능하다.

**존재 여부는 열거로 판정한다.** `Item(name)`이 던지는 예외를 "없음"의 근거로 삼으면 안 된다.
COM 오류는 "없음"과 "일시적 실패"를 구분해 주지 않으므로, 실패를 없음으로 읽으면 중복 생성으로
이어진다(fail-open). `Count` + `Item(i)`로 열거해 이름을 비교하는 쪽이 positive evidence다.

부동소수 비교는 `math.isclose(a, b, rel_tol=0.0, abs_tol=TOLERANCE)`로 한다.
**`rel_tol=0.0`을 반드시 명시한다.** 생략하면 기본 `rel_tol=1e-09`가 살아 있어 값이 커질수록
허용 오차가 함께 커지고, 큰 pad 높이의 갱신 요청이 조용히 무시된다.

`edit()`은 **재진입을 금지**한다. 중첩 `OpenEdition`의 의미는 검증되지 않았고, CATIA가 편집
상태를 하나만 유지한다면 안쪽 `CloseEdition`이 바깥 세션을 먼저 닫아 짝이 어긋난다.

생성은 원자적이지 않다. `Sketches.Add`/`AddNewPad`가 성공한 뒤 `Name` 쓰기가 실패하면 기본
이름의 형상이 모델에 남는다. Pad를 지우면 Sketch까지 연쇄 삭제되므로 자동 롤백은 오히려
위험하다. 이 경우 **남은 객체의 실제 이름을 담아 보고**해서 호출자가 재시도로 형상을 더 쌓지
않게 한다.

추가 예외: `AmbiguousNameError(Auto3dxError)`, `PartialCreationError(Auto3dxError)`.

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
    # selection은 형상 삭제에만 필요하다. Catia.active_part()가 넣어 준다.
    def __init__(self, com_object: Any, selection: Any = None) -> None: ...

    @property
    def com_object(self) -> Any: ...

    @property
    def name(self) -> str: ...

    # 아래 셋은 모두 최초 접근 시 생성 후 캐시
    @property
    def parameters(self) -> "ParameterCollection": ...

    @property
    def sketches(self) -> "SketchCollection": ...

    @property
    def part_design(self) -> "PartDesign": ...

    def update(self) -> None: ...            # 실패 시 PartUpdateError. save 호출 금지.
```

### 6.5 `auto_3dx/parameters/parameter.py`

```python
LENGTH_KIND: str = "Length"                  # type(com_object).__name__
LENGTH_MAGNITUDE: str = "Length"             # CreateDimension의 iMagnitude
MILLIMETRE: str = "mm"
SUPPORTED_LENGTH_UNITS: frozenset[str] = frozenset({MILLIMETRE})
NAME_SEPARATOR: str = "\\"

# 모듈 수준 validator. create/ensure와 set이 공유한다.
def validate_length_unit(unit: str) -> None: ...      # UnsupportedUnitError
def validate_length_value(value: float) -> float: ... # ParameterTypeError, float 반환
def validate_parameter_name(name: str) -> str: ...    # ParameterNameError

@dataclasses.dataclass(frozen=True)
class ParameterInfo:
    name: str
    short_name: str
    kind: str
    value: Any
    unit: str | None

class Parameter:
    def __init__(self, com_object: Any) -> None: ...

    @property
    def com_object(self) -> Any: ...

    @property
    def name(self) -> str: ...               # CATIA가 준 값 그대로 (정규화될 수 있음)

    @property
    def short_name(self) -> str: ...         # 마지막 NAME_SEPARATOR 뒤

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
    def create_length(self, name: str, value: float,
                      unit: str = MILLIMETRE) -> Parameter: ...
    def ensure_length(self, name: str, value: float,
                      unit: str = MILLIMETRE) -> Parameter: ...
    def remove(self, name: str) -> None: ...   # Parameters.Remove(정규화 이름)

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

### 6.9 `auto_3dx/geometry/sketch.py`

```python
SUPPORT_XY: str = "XY"
SUPPORT_YZ: str = "YZ"
SUPPORT_ZX: str = "ZX"
SUPPORTED_SKETCH_SUPPORTS: frozenset[str] = frozenset({SUPPORT_XY, SUPPORT_YZ, SUPPORT_ZX})
AXIS_TOLERANCE: float = 1e-9

class SketchEditor:
    """Only valid inside `Sketch.edit()`. Wraps Factory2D."""
    @property
    def com_object(self) -> Any: ...
    def point(self, x: float, y: float) -> Any: ...
    def line(self, x1: float, y1: float, x2: float, y2: float) -> Any: ...
    def circle(self, center_x: float, center_y: float, radius: float) -> Any: ...
    def rectangle(
        self,
        width: float,
        height: float,
        origin_x: float = 0.0,
        origin_y: float = 0.0,
    ) -> list[Any]: ...

class Sketch:
    def __init__(self, com_object: Any) -> None: ...
    @property
    def com_object(self) -> Any: ...
    @property
    def name(self) -> str: ...
    def rename(self, name: str) -> None: ...
    def support(self) -> str | None: ...        # "XY"/"YZ"/"ZX", None if unrecognised
    def axis_data(self) -> tuple[float, ...]: ...
    def element_names(self) -> list[str]: ...
    @contextlib.contextmanager
    def edit(self) -> Iterator[SketchEditor]: ...   # CloseEdition in finally
    def __repr__(self) -> str: ...

class SketchCollection:
    # needs Part for OriginElements + MainBody; selection only for remove()
    def __init__(self, part_com_object: Any, selection: Any = None) -> None: ...
    @property
    def count(self) -> int: ...
    def list(self) -> list[Sketch]: ...
    def names(self) -> list[str]: ...
    def get(self, name: str) -> Sketch: ...          # SketchNotFoundError
    def create(self, name: str, support: str = SUPPORT_XY) -> Sketch: ...
    def ensure(self, name: str, support: str = SUPPORT_XY) -> Sketch: ...
    def remove(self, name: str) -> None: ...
    def __len__(self) -> int: ...
    def __iter__(self) -> Iterator[Sketch]: ...
    def __contains__(self, name: object) -> bool: ...
```

`edit()`은 `OpenEdition()`으로 얻은 `Factory2D`를 넘기고, 예외가 나도 `finally`에서
`CloseEdition()`을 호출한다. 열린 편집 상태를 남기면 안 된다.

`create()`는 `Sketches.Add(plane)` 직후 `Name`을 설정한다(이름 쓰기는 실측 가능).
이름이 이미 있으면 `SketchAlreadyExistsError`.

### 6.10 `auto_3dx/geometry/part_design.py`

```python
LENGTH_TOLERANCE: float = 1e-9

class Pad:
    def __init__(self, com_object: Any) -> None: ...
    @property
    def com_object(self) -> Any: ...
    @property
    def name(self) -> str: ...
    @property
    def height(self) -> float: ...               # FirstLimit.Dimension.Value
    def set_height(self, height: float, unit: str = MILLIMETRE) -> None: ...
    def sketch(self) -> Sketch: ...              # Pad.Sketch
    def __repr__(self) -> str: ...

class PartDesign:
    # selection only for remove_pad()
    def __init__(self, part_com_object: Any, selection: Any = None) -> None: ...
    @property
    def pads(self) -> list[Pad]: ...
    def get_pad(self, name: str) -> Pad: ...     # FeatureNotFoundError
    def create_pad(self, name: str, sketch: Sketch, height: float,
                   unit: str = MILLIMETRE) -> Pad: ...
    def ensure_pad(self, name: str, sketch: Sketch, height: float,
                   unit: str = MILLIMETRE) -> Pad: ...
    def remove_pad(self, name: str) -> None: ...
```

`Part`는 다음을 추가로 노출한다(둘 다 최초 접근 시 생성 후 캐시):

```python
part.sketches      -> SketchCollection
part.part_design   -> PartDesign
```

추가 예외:

```text
SketchNotFoundError(Auto3dxError)
SketchAlreadyExistsError(Auto3dxError)
SketchSupportMismatchError(Auto3dxError)
FeatureNotFoundError(Auto3dxError)
FeatureConflictError(Auto3dxError)
UnsupportedSupportError(Auto3dxError)
```

### 6.7 `auto_3dx/__init__.py`

공개 이름은 wrapper 타입 전체와 예외 계층 전체다.

```python
# wrappers
Catia, Part, Parameter, ParameterCollection, ParameterInfo,
Sketch, SketchCollection, SketchEditor, Pad, PartDesign

# errors
Auto3dxError, CatiaConnectionError, Com3dxNotFoundError,
FeatureConflictError, FeatureNotFoundError,
NoActiveEditorError, NoActivePartError,
ParameterAlreadyExistsError, ParameterNameError, ParameterNotFoundError,
ParameterTypeError, PartUpdateError,
SketchAlreadyExistsError, SketchNotFoundError, SketchSupportMismatchError,
UnsupportedSupportError, UnsupportedUnitError
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
