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

### 1.1.1 사용자 파라미터와 feature 내부 파라미터 (실측)

형상을 만들면 CATIA가 그 feature의 치수를 파라미터로 **자동 노출**한다. 패드 하나와
사각형 스케치 하나를 만든 뒤 실측한 결과:

```text
Parameters.Count                        = 18   <- 자동 생성분 15개 포함
RootParameterSet.DirectParameters.Count = 3    <- 사람이 만든 것만
RootParameterSet.AllParameters.Count    = 3
RootParameterSet.ParameterSets.Count    = 0
```

자동 생성되는 것의 예:

```text
<Part>\PartBody\<Pad>\FirstLimit\Length              패드의 실제 돌출 길이
<Part>\PartBody\<Pad>\ThickThin1 / ThickThin2        thin pad 두께
<Part>\PartBody\<Pad>\Activity                       feature 활성/억제
<Part>\PartBody\<Pad>\<Sketch>\Coincidence.3\Mode    스케치 구속의 모드
<Part>\PartBody\<Pad>\<Sketch>\Coincidence.3\Activity
```

**이것들은 무의미한 값이 아니다.** formula로 패드 두께를 사용자 파라미터에 연동하려면
대상이 바로 `...\<Pad>\FirstLimit\Length`다. 따라서 숨기면 안 된다.

다만 성격이 다르다. 자동 생성분은 feature 경로를 이름으로 쓰므로 **패드 이름을 바꾸면
경로가 통째로 바뀌고**, feature 하나당 15개씩 늘어난다. "이 파트의 파라미터가 뭐냐"는
물음에 답할 때 쓸 목록이 아니다.

그래서 둘 다 노출하되 구분한다.

```text
parameters.list()             -> Parameters.Item(1..Count)             전체
parameters.user_parameters()  -> RootParameterSet.DirectParameters     사람이 만든 것만
```

### 1.1.2 Length 외 파라미터 타입과 단위 (실측, probes 23·24)

```text
CreateReal(iName, iValue: double)   -> RealParam    Value 쓰기 가능
CreateInteger(iName, iValue: long)  -> IntParam     Value 쓰기 가능
CreateString(iName, iValue: BSTR)   -> StrParam     Value 쓰기 가능
CreateBoolean(iName, iValue: bool)  -> BoolParam    Value 쓰기 가능
CreateDimension(iName, iMagnitude, iValue: double)  -> magnitude에 따라 다름
잘못된 magnitude                    -> com_error
```

**`CreateDimension`의 wrapper 타입은 magnitude마다 다르다.** 파생 타입이 붙는 것은
`Length`와 `Angle` 둘뿐이고 나머지는 전부 generic `Dimension`이다.

```text
"Length" -> kind=Length     "Angle"  -> kind=Angle
"Mass"   -> kind=Dimension  "Volume" -> kind=Dimension  "Time" -> kind=Dimension
```

따라서 **`type(obj).__name__`으로는 Mass와 Time을 구분할 수 없다.** 정체는
`Dimension.Unit`에서 읽는다 (실측).

```text
Length : Unit.Magnitude='Length' Unit.Symbol='mm'  Unit.Name='Millimeter'
Angle  : Unit.Magnitude='Angle'  Unit.Symbol='deg' Unit.Name='Degree'
Mass   : Unit.Magnitude='Mass'   Unit.Symbol='kg'  Unit.Name='Kilogram'
Volume : Unit.Magnitude='Volume' Unit.Symbol='m3'  Unit.Name='Cubic meter'
```

`RealParam` / `IntParam` / `StrParam` / `BoolParam`에는 `Unit`이 없다(무단위).
네 타입 모두 `ValuateFromString`을 갖지만 검증하지 않았다.

**단위 카탈로그** (`Parameters.Units`, 실측):

```text
Units.Count = 1887,  서로 다른 magnitude = 339
Unit 항목   = (Name, Magnitude, Symbol)   예: ('Millimeter', 'Length', 'mm')
Length 67개 : mm m cm km in ft micron yard ...
Angle  12개 : deg rad grad DegMinSec turn mrad ...
Mass   26개 : kg g mg T lb oz slug ...
Time   19개 : s ms h mn day a week ...
Volume 56개 : m3 mm3 cm3 in3 ft3 L gal ...
```

**중요: `Value`는 언제나 파라미터 자신의 내부 단위로 읽고 쓴다.** `Length.Value = 150.0`은
어떤 경우에도 150mm다. 단위 변환은 검증하지 않았으므로 **라이브러리는 단위를 변환하지
않는다.** 단위 인자는 파라미터의 실제 단위와 일치하는지 확인하는 용도로만 쓴다.

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

### 1.2.1 Pocket과 Formula (실측, `scripts/probes/16_pocket_and_formula.py`)

```text
ShapeFactory.AddNewPocket(iSketch, iHeight)                  -> Pocket
Relations.CreateFormula(iName, iComment, iOutputParameter, iFormulaBody) -> Formula
Relations.Count / Item(i) / Remove(i) / GetItem(name)
Parameters.GetNameToUseInRelation(iObject)                   -> str
```

**Pocket은 Pad의 구조적 쌍둥이다.** 읽기 가능 속성이 완전히 같다.

```text
Application, DirectionOrientation, DirectionType, FirstLimit, IsSymmetric,
IsThin, MergeEnd, Name, NeutralFiber, Parent, SecondLimit, Sketch
FirstLimit.Dimension.Value == AddNewPocket에 넘긴 깊이 (실측 5.0)
Name 쓰기 가능
```

따라서 Pad wrapper를 공통 기반으로 일반화하고 Pocket은 그 위에 얹는다.

**수식에 쓸 이름은 `Parameter.name`과 다르다.** 반드시
`Parameters.GetNameToUseInRelation(obj)`로 얻는다.

```text
사용자 파라미터
  Parameter.name           = '3D Shape00422534\AUTO3DX_THICKNESS'
  GetNameToUseInRelation() = 'AUTO3DX_THICKNESS'              <- 접두어 없음

feature 내부 파라미터 (pad 높이)
  GetNameToUseInRelation() = 'PartBody\AUTO3DX_BASE_PAD\FirstLimit\Length'
```

`.name`으로 수식 문자열을 조립하면 깨진다.

**formula는 실제로 모델을 구동한다** (실측).

```text
CreateFormula('F', 'comment', <pad FirstLimit Dimension>, 'AUTO3DX_THICKNESS * 2')
  driver 12.0 -> Part.Update() -> pad.height 24.0
  driver 20.0 -> Part.Update() -> pad.height 40.0
```

`Formula`가 읽어주는 것:

```text
Value          수식 본문 문자열 ('AUTO3DX_THICKNESS * 2')
Activated      True
Comment        생성 시 넘긴 주석
NbInParameters 1
Name, Hidden, IsConst, Context, NbOutParameters
쓰기 가능: Comment, Hidden, IsConst, Name
메서드: Activate, Deactivate, Modify(iValue), Rename(iName),
        GetInParameter(i), GetOutParameter(i)
```

`Relations.Remove(index)`로 제거된다 (1-based). 제거 후 `Count`가 정상적으로 줄고
`Part.Update()`도 성공한다.

**formula를 제거해도 마지막으로 계산된 값은 되돌아가지 않는다** (실측). 대상 파라미터에는
그 값이 그대로 남으므로, 원래 값으로 복원하려면 제거 후 직접 써 줘야 한다.

```text
pad height 12.0 -> formula 'THICKNESS * 3' 적용 -> 30.0
  -> formula 제거 -> pad height 30.0  (12.0으로 돌아가지 않음)
```

**Pocket을 제거해도 그 스케치는 함께 지워지지 않는다** (실측). Pad 제거는 스케치까지
연쇄 삭제되지만(1.2 참조) Pocket은 그렇지 않다. 정리할 때는 스케치를 따로 지워야 한다.

```text
Pad 제거    : Shapes 1->0, Sketches 1->0   (연쇄됨)
Pocket 제거 : Shapes 1->0, Sketches 그대로  (연쇄 안 됨)
```

### 1.2.4 스케치 제약 (실측, probes 20·21·22)

```text
Sketch.Constraints                                  -> Constraints
Constraints.AddMonoEltCst(iCstType: int, iElem)     -> Constraint
Constraints.AddBiEltCst(iCstType: int, iFirst, iSecond) -> Constraint
Constraints.Count / Item(i) / Remove(i)   [1-based]
Constraints.BrokenConstraintsCount / UnUpdatedConstraintsCount
Constraint: Name, Type, Status, Dimension, Mode, ...
```

**제약은 편집 세션 안에서만 걸린다.** 이게 가장 중요한 사실이다.

```text
CloseEdition() 이후 AddMonoEltCst(...)  -> 전부 com_error
OpenEdition()~CloseEdition() 사이        -> 동작
```

그리고 인자는 **raw `Line2D` / `Circle2D`를 그대로** 넘긴다. `CreateReferenceFromObject`로
감싼 `Reference`는 거부된다. Part Design의 face/edge 참조와 정반대다.

따라서 제약 생성 API는 `edit()` 안에서만 존재하는 `SketchEditor`에 둔다.

검증된 제약 타입 (요청 코드 -> CATIA가 실제로 만든 것):

```text
10 Horizontality    -> 'Parallelism.1'      Type=8
13 Verticality      -> 'Parallelism.2'      Type=8
 5 Length           -> 'Length.3'           Type=5    <- Dimension 있음
14 Radius           -> 'Radius.4'           Type=14   <- Dimension 있음
11 Perpendicularity -> 'Perpendicularity.5' Type=11
 8 Parallelism      -> 'Parallelism.6'      Type=8
 1 Distance         -> 'Offset.7'           Type=1    <- Dimension 있음
 2 On               -> 'Coincidence.8'      Type=2
 4 Tangency         -> 'Tangency.9'         Type=4
 3 Concentricity    -> 'Concentricity' (probe 27에서 서로 다른 원 2개로 검증)
```

**요청한 타입과 결과 타입이 다를 수 있다.** Horizontality/Verticality는 둘 다 Parallelism
(Type 8)으로 정규화된다. 따라서 만들어진 제약을 타입 코드로 되찾으려 하면 안 된다.

**치수 제약의 `Dimension`은 읽기·쓰기 모두 가능하다** (실측).

```text
'Length.3' 40.0 -> 45.0    'Radius.4' 4.0 -> 9.0    'Offset.7' 25.0 -> 30.0
쓰기 후 Part.Update() 성공, BrokenConstraintsCount 0 유지
```

이것이 파라메트릭 모델의 핵심이다. formula가 구동할 대상이 된다.

건강 신호: `Status == 0`이 정상이고, `BrokenConstraintsCount` / `UnUpdatedConstraintsCount`로
스케치 상태를 확인할 수 있다.

**미검증:** `Constraints.Remove(i)`는 호출해 보지 않았다. 제약 삭제는 구현하지 않는다.

### 1.2.7 사용자 정의 평면 (부분 검증, probe 29)

지금은 원점 평면 3개(XY/YZ/ZX)에만 스케치를 만들 수 있다. offset 평면까지는 길이 났다.

```text
Part.HybridShapeFactory -> HybridShapeFactory   (선언 타입은 generic Factory, 런타임 캐스팅)
HybridBodies.Add() -> HybridBody                (기하 세트. 평면을 넣을 곳)
HybridShapeFactory.AddNewPlaneOffset(iPlane, iOffset, iOrientation) -> HybridShapePlaneOffset
HybridBody.AppendHybridShape(iHybridShape)      (이걸 거치지 않으면 평면이 쓸 수 없다)
```

검증된 것:

```text
AddNewPlaneOffset(raw PlaneXY, 30.0, False) + AppendHybridShape + Part.Update() -> 성공
되읽기: Offset.Value = 30.0, Plane.DisplayName = 'xy plane', Orientation = 1 (int)
Sketches.Add(raw hybrid shape) -> Sketch        (Reference로 감쌀 필요 없음)
그 스케치에 사각형 + Part.Update()              -> 성공
```

**미검증(구현하지 않는다):**

```text
그 스케치에 pad          -> AddNewPad 실패 (0x80020009). 원인 미파악
AddNewPlaneAngle(...)    -> 생성은 되지만 Part.Update() 실패
```

`iOrientation`은 `VT_BOOL`로 넘기는데 되읽기는 `VT_I4` 정수다. 대응 관계가 문서에 없으므로
`False == 0`이라고 가정하면 안 된다.

### 1.2.6 곡선 스케치 요소 (실측, probe 27)

`Factory2D`에서 직선·사각형 외의 요소가 전부 검증됐다. 생성 + `Part.Update()` 모두 성공했고,
닫힌 원을 프로파일로 쓴 pad도 성공했다. **곡선 프로파일은 pad 된다.**

```text
CreateCircle(iCenterX, iCenterY, iRadius, iStartParam, iEndParam) -> Circle2D
CreateClosedCircle(iCenterX, iCenterY, iRadius)                   -> Circle2D
CreatePoint(iX, iY)                                               -> Point2D
CreateControlPoint(iX, iY)                                        -> ControlPoint2D
CreateSpline(iPoles)                                              -> Spline2D
```

`CreateSpline`은 입력 배열을 받는다. `ControlPoint2D` 3개로 검증했다. `Point2D`도 되는지는
시험하지 않았다.

되읽기에 함정이 있다.

```text
Circle2D.Radius / GeometricType / StartPoint / EndPoint  -> 동작
Circle2D.CenterPoint  -> type library에 있는데 COM 오류. 제공하지 않는다.
Point2D               -> X/Y 속성이 아예 없다. GetCoordinates([0.0, 0.0]) -> (0.0, 30.0)
Spline2D.GetNumberOfControlPoints() -> int가 아니라 float
```

`Construction`은 `Circle2D` / `Point2D` / `Spline2D` 모두 쓰기 가능하고, `True`로 두면 그
요소가 pad 프로파일에서 빠진다.

**`CatConstraintType`에 `Diameter` 멤버가 아예 없다.** 원 크기는 `Radius`(14)뿐이다. 지름
구속을 만들어 내면 안 된다.

`CreateCircle`의 `iStartParam` / `iEndParam` 단위는 확인하지 않았다. 라디안으로 넘겨서
동작했지만 그것이 라디안임을 증명한 것은 아니다.

### 1.2.3 Shaft / Groove / Mirror (실측, probes 17·18·19)

```text
ShapeFactory.AddNewShaft(iSketch)   -> Shaft
ShapeFactory.AddNewGroove(iSketch)  -> Groove
ShapeFactory.AddNewMirror(iMirroringElement) -> Mirror
Part.CreateReferenceFromObject(iObject) -> Reference
Part.FindObjectByName(iObjName)         -> 해당 객체 (Pad / Body / AnyObject 확인)
```

**Shaft와 Groove는 회전 feature다.** Pad/Pocket과 달리 `FirstLimit`이 아니라
`FirstAngle` / `SecondAngle`(`Angle` 객체)을 갖는다.

```text
Angle.Value  읽기/쓰기 모두 가능
기본값       FirstAngle 360.0, SecondAngle 0.0     (단위 deg)
90.0으로 설정 후 Part.Update() 성공
그 외 읽기 가능: Unit, ReadOnly, RangeMin/Max, Comment, ...
```

**축이 필요하다.** 스케치에 `CenterLine`을 지정해야 한다. 쓰기 가능하며, 프로파일은 축에서
떨어져 있어야 한다.

```python
with sketch.edit() as editor:
    editor.rectangle(10.0, 6.0, origin_x=20.0, origin_y=0.0)   # 축에서 떨어진 프로파일
    axis = editor.line(0.0, 0.0, 0.0, 20.0)
sketch.com_object.CenterLine = axis
```

**Mirror는 평면을 받는다.** `OriginElements.PlaneYZ`를 그대로 넘기면 동작한다. BRep 이름이
필요 없는 유일한 대칭/변환 기능이다.

### 1.2.2.1 `AddNew*` 성공이 feature 유효를 뜻하지 않는다 (중요)

실측:

```text
AddNewStiffener(sketch)   -> Stiffener 객체 반환.  이후 Part.Update() 실패
AddNewRectPattern(...)    -> RectPattern 객체 반환. 이후 Part.Update() 실패
```

객체는 트리에 생겼는데 모델이 재계산에 실패한다. 즉 **생성 호출이 성공해도 모델은 깨져 있을
수 있고, 그 feature는 트리에 남는다.**

따라서:

- probe에서 "검증됨"의 기준은 **생성 성공 + `Part.Update()` 성공**이다. 생성만 성공한 것은
  검증되지 않은 것으로 취급한다.
- 라이브러리의 `create_*`는 `Part.Update()`를 호출하지 않으므로, 호출자가 update하고
  `PartUpdateError`를 처리해야 한다. **실패해도 feature는 모델에 남으므로** 호출자가 지워야
  한다. 이 점을 docstring에 명시한다.

이 기준으로 Stiffener와 Pattern은 **미검증**이며 구현하지 않는다.

### 1.2.2 아직 참조 레이어가 없어 막힌 Part Design 기능

`ShapeFactory`는 `AddNew*`를 90개 노출한다. 스케치만 받는 것은 지금 구현할 수 있지만,
면·모서리를 받는 것은 그 대상을 지목할 방법이 없어 불가능하다.

```text
구현 가능 (스케치만)      AddNewPad, AddNewPocket, AddNewShaft, AddNewGroove,
                          AddNewStiffener
스케치 2개                AddNewRib(iSketch, iCenterCurve), AddNewSlot(...)
면/모서리 참조 필요        AddNewChamfer(iObjectToChamfer, ...)
                          AddNewEdgeFilletWithConstantRadius(iEdgeToFillet, ...)
                          AddNewShell(iFaceToRemove, ...)
                          AddNewThickness(iFaceToThicken, ...)
                          AddNewDraft(iFaceToDraft, ...)
                          AddNewHole(iSupport, iDepth)
feature + 방향 참조 필요   AddNewMirror(iMirroringElement)
                          AddNewRectPattern(인자 12개), AddNewCircPattern(12개)
```

면·모서리 참조는 `Part.CreateReferenceFromObject` / BRep 이름이 필요한데, BRep 이름은
모델이 바뀌면 깨지므로 별도 설계가 필요하다. **참조 레이어가 생기기 전까지 이 기능들은
구현하지 않는다.** 단 아래 1.2.2.2에서 모서리 참조를 얻는 경로 하나가 뚫렸다.

### 1.2.2.2 모서리 참조를 얻는 경로 (실측, probe 28)

`Selection.Search`로 솔리드의 topology를 열거할 수 있다. **쿼리 문자열이 정확해야 한다.**

```text
Search('Face,all')           -> COM 오류
Search('Edge,all')           -> COM 오류
Search('Topology.Face,all')  -> 9개, wrapper 타입 PlanarFace
Search('Topology.Edge,all')  -> 29개, wrapper 타입 RectilinearTriDimFeatEdge
```

`Search` 자체는 void를 반환하고 `Selection`을 변경한다. 따라서 `Clear()` → `Search(query)`
→ `Count` / `Item(i)` 순서로 읽는다.

검색 결과를 `Reference`로 바꾸는 방법은 **하나뿐이다.**

```text
Part.CreateReferenceFromObject(검색 결과)  -> 실패 (면·모서리 모두)
SelectedElement.Reference                  -> Reference (성공)
```

그 `Reference`의 `Name`과 `DisplayName`은 동일한 BRep 문자열이다.

```text
Selection_REdge:(Edge:(Face:(Brp:((Brp:(Pad.21;1);Brp:(Pad.1;1)));None:();Cf16:());...)
```

**그리고 fillet이 처음으로 검증됐다.**

```text
AddNewEdgeFilletWithConstantRadius(모서리 Reference, 1, 반지름)
  -> 생성 + Part.Update() 성공 -> 검증됨
```

면 Reference를 fillet이나 chamfer에 넣으면 propagation 0·1·2 전부 실패한다. fillet은
모서리를 요구한다. `AddNewChamfer`는 생성은 되지만 update가 실패했다. propagation/mode/
orientation 정수의 의미가 type library에 없어서(enum 메타데이터 없는 순수 `VT_I4`) 어떤
값이 맞는지 아직 모른다.

**첫 fillet 이후의 모든 시도는 update가 실패했다.** 그 실행에서 모든 Reference를 수정 전에
미리 잡아뒀으므로, fillet이 topology를 바꿔 기존 Reference가 무효가 된 것으로 보인다.
아직 가설이며 probe 31에서 확인한다. 확인되면 **수정마다 재열거**가 규칙이 되고 라이브러리가
그것을 강제해야 한다.

남은 설계 문제는 "어느 모서리인가"를 지목하는 방법이다. 검색 순서(index)는 재빌드를 넘어
보존된다는 근거가 없고 BRep 문자열은 구조적으로 깨진다. 측정(1.4)으로 모서리를 기하학적으로
골라내는 방향을 probe 31에서 조사한다.

### 1.2.5 Rib / Stiffener / Pattern (실측, probe 24)

```text
AddNewRib(iSketch, iCenterCurve)  -> Rib       생성 + Update 성공 -> 검증됨
AddNewSlot(iSketch, iCenterCurve) -> Slot      생성 + Update 성공 -> 검증됨
AddNewStiffener(iSketch)          -> Stiffener 생성은 되나 Update 실패 (2회) -> 미검증
AddNewRectPattern(...)                         부분 검증 (아래)
```

Rib과 Slot은 프로파일 스케치와 경로(center curve) 스케치 **두 개**를 받는다. Slot은 Rib의
절삭 버전이다. 실측 조합:

```text
프로파일 : YZ 평면에 사각형
경로     : XY 평면에 직선
```

둘 다 `Sketch`로 **프로파일만** 되읽을 수 있다. 경로 스케치를 되읽는 방법은 없다.

Stiffener는 프로파일을 두 번 바꿔 시도했지만 두 번 다 `Part.Update()`가 실패했다.
1.2.2.1 기준에 따라 **미검증이며 구현하지 않는다.**

**Pattern은 방향 인자가 까다롭다** (probe 25 실측).

```text
AddNewRectPattern(pad, 2, 1, 60, 60, 1, 1, dir, dir, False, False, 0)
  dir = raw Line2D            -> 생성됨, Update 실패
  dir = Reference(Line2D)     -> 생성됨, Update 실패
  dir = Reference(PlaneXY)    -> 생성됨, Update 성공
  dir = raw PlaneYZ           -> 생성됨, Update 실패 (probe 18)
```

즉 방향은 **원점 평면으로 만든 `Reference`** 여야 한다. 세 평면(XY/YZ/ZX) 모두 생성과
update가 성공한다 (probe 26).

패턴 자신의 파라미터는 전부 읽히고, 넘긴 값이 그대로 들어간다.

```text
NumberInDir1 = 2     Spacing1 = 60.0     RotationAngle = 0.0
NumberInDir2 = 1     Spacing2 = 60.0     RowInDir1/2 = 1
RectPattern 읽기 가능: FirstDirectionRepartition (LinearRepartition),
                       FirstOrientation, ItemToCopy, FirstRectangularPatternParameters
```

따라서 개수와 간격은 formula로 구동할 수 있다.

**어느 평면이 어느 축을 만드는지는 probe 30에서 측정으로 확정했다.** 되읽기 속성이 없어
눈으로 봐야 하는 문제로 보였지만, 측정(1.4)이 열리면서 숫자로 풀렸다. 패턴이 **추가한
재료의 무게중심**을 질량 균형으로 계산해 원본 pad 무게중심과 비교했다.

```text
C_added = (V_after * C_after - V_before * C_before) / (V_after - V_before)
```

평면 3개 x 배치 2종(2개/60mm, 3개/100mm)에서 예측과 소수점 셋째 자리까지 일치했다.

```text
dir1 = Reference(PlaneXY) -> -X      dir2 = Reference(PlaneXY) -> -Y
dir1 = Reference(PlaneYZ) -> -Y      dir2 = Reference(PlaneYZ) -> -Z
dir1 = Reference(PlaneZX) -> -Z      dir2 = Reference(PlaneZX) -> -X
```

즉 **dir1은 평면의 첫 축, dir2는 둘째 축이고 둘 다 음방향이다.** `iIsReversedDir1=True`로
부호가 뒤집힌다(정확히 +60mm 측정). 전체 인자 이름은 type library 기준으로 이렇다.

```text
AddNewRectPattern(iShapeToCopy, iNbOfCopiesInDir1, iNbOfCopiesInDir2,
    iStepInDir1, iStepInDir2, iShapeToCopyPositionAlongDir1,
    iShapeToCopyPositionAlongDir2, iDir1, iDir2, iIsReversedDir1,
    iIsReversedDir2, iRotationAngle) -> RectPattern
```

**dir1과 dir2가 같은 축이 되면 `Part.Update()`가 실패하고 깨진 feature가 트리에 남는다.**
(dir1=PlaneXY, dir2=PlaneZX 둘 다 X축 -> 실패. dir1을 PlaneYZ로 바꾸자 같은 dir2가 성공.)
라이브러리가 COM 호출 전에 직접 거부해야 한다.

공개 API는 평면이 아니라 **축**으로 말한다(`"X"`, `"-X"`, ...). 평면을 인자로 받으면 검증할
수 없는 대응 관계의 책임을 호출자에게 떠넘기게 된다.

### 1.4 모델 측정 (실측, probe 30)

`Part.Update()` 성공은 feature가 재빌드됐다는 뜻일 뿐, 의도한 결과가 나왔다는 뜻이 아니다.
아무것도 깎지 않는 pocket도 update는 잘 통과한다(2.6). 측정으로 그 공백을 메운다.

```text
Editor.GetService(iService) -> Service

받아들이는 이름 : 'InertiaService', 'InertiaBoxService', 'MeasurableService'
거부하는 이름   : 'CATIAInertiaService', 'SPAWorkbench'   (COM 오류)

InertiaService.GetInertiaElement(item) -> Inertia
  Inertia.GetVolume() / GetArea() / GetMass() -> double
  Inertia.GetCOGPosition(oX, oY, oZ)   # 참조 out 3개, pywin32가 tuple로 반환
InertiaBoxService.GetInertiaBoxElement(item) -> InertiaBox
  InertiaBox.GetBoundingBox(oOrigin, oLengths)
```

**모든 값이 SI(m, m3)로 온다.** 나머지 API는 mm를 쓰므로 반드시 환산해야 한다. 20x20x10 mm
pad는 2e-06 m3다. 환산을 놓치면 1000배 또는 10억배 틀린 값이 조용히 나온다.

`GetBoundingBox`는 인자 없이 호출하면 type mismatch다. **3개짜리 시퀀스 2개를 넘겨야 하고,
반환값으로 `(origin, lengths)`를 돌려준다** (인자를 바꾸는 방식이 아니다).

```text
box.GetBoundingBox((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
```

**함정: `GetInertiaBoxElement`는 축 정렬 bounding box가 아니다.** 솔리드의 **주관성축**에
정렬된다. 단순한 블록에서는 전역 축과 일치해서 쓸 만해 보이는데 그게 바로 함정이고, 형상이
비대칭이 되면 상자가 회전한다. 패턴 하나를 걸었더니 세 축이 동시에 늘어난 것으로 나왔다.
판정에 쓰면 안 된다.

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

**파라미터를 열거할 때는 무엇과 무엇을 비교하는지가 결정적이다.** 두 가지를 실측으로 확인했다.

- `CreateDimension`은 이름을 **정규화해서 저장한다.** `"Span"`으로 만든 파라미터의 `name`은
  `"3D Shape1\Span"`이다. 그래서 `parameter.name == 요청이름`만 비교하면 방금 만든 파라미터도
  못 찾고, 중복 검사가 **전부 통과한다.** `short_name`까지 함께 비교해야 한다.
- 열거 대상은 `list()`가 아니라 `user_parameters()`다. feature 내부 파라미터는 feature 경로로
  이름이 붙어(`Pad.1\FirstLimit\Length`) short name이 `"Length"`처럼 사용자가 쓸 만한 이름과
  충돌한다. `list()`를 열거하면 정당한 생성을 거부한다.

이 조합은 **unit 테스트로 잡히지 않았다.** 기존 테스트가 모두 fake에 정규화되지 않은 이름을 미리
심어뒀기 때문이다. fake도 실제 COM처럼 정규화 이름을 만들어야 하고, "만들고 바로 다시 만들기"를
검사하는 테스트가 있어야 한다(`tests/unit/test_duplicate_name_detection.py`).

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

### 6.8 `auto_3dx/core/application.py` 확장 (여러 editor)

`Application.ActiveEditor`가 UI 탭 전환을 즉시 따라오지 않는 경우를 실측했다. 탭은 새
파트인데 COM은 이전 파트를 가리켰다. 엉뚱한 파트를 편집하는 사고를 막으려면 editor를
직접 고를 수 있어야 한다.

실측한 것 (`Application.Editors`):

```text
Editors.Count = 4
Editors.Item(i)  1-based
  [1] CATIAEditor4 | ActiveObject 접근 시 com_error      <- 이런 editor가 섞여 있다
  [2] CATIAEditor0 | Part 'ohShape00422533'
  [3] CATIAEditor5 | VPMRootOccurrence
  [4] CATIAEditor6 | Part '3D Shape00422534'
editor.Name / editor.ActiveObject / editor.Selection
```

`ActiveObject`가 실패하는 editor가 실제로 존재하므로, 열거는 **실패한 항목을 건너뛰고
계속**해야 한다. 하나 때문에 전체가 죽으면 안 된다.

```python
@dataclasses.dataclass(frozen=True)
class EditorInfo:
    name: str                 # "CATIAEditor6"
    object_kind: str | None   # "Part" / "VPMRootOccurrence" / None (읽기 실패)
    object_name: str | None   # "3D Shape00422534" / None
    is_part: bool

class Catia:
    def editors(self) -> "list[EditorInfo]": ...
    def parts(self) -> "list[Part]": ...          # Part를 편집 중인 editor만, 각자 Selection 연결
    def part_named(self, name: str) -> Part: ...  # 없으면 NoActivePartError,
                                                  # 둘 이상이면 AmbiguousNameError
```

`parts()`와 `part_named()`가 돌려주는 `Part`에는 **그 editor의 `Selection`**을 넣어 준다.
다른 editor의 selection을 쓰면 엉뚱한 창에서 삭제가 일어난다.

기존 `active_editor()` / `active_part()`는 그대로 둔다.

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

### 6.11 `auto_3dx/geometry/part_design.py` 확장 (Pocket)

Pad와 Pocket은 COM 구조가 같으므로 공통 기반으로 일반화한다.

```python
PAD_KIND: str = "Pad"
POCKET_KIND: str = "Pocket"

class SketchFeature:
    """Pad/Pocket 공통. FirstLimit.Dimension.Value를 depth로 읽고 쓴다."""
    def __init__(self, com_object: Any) -> None: ...
    @property
    def com_object(self) -> Any: ...
    @property
    def name(self) -> str: ...
    @property
    def depth(self) -> float: ...            # FirstLimit.Dimension.Value
    def set_depth(self, depth: float, unit: str = MILLIMETRE) -> None: ...
    def sketch(self) -> Sketch: ...
    def depth_parameter(self) -> Parameter: ...   # FirstLimit.Dimension, formula 대상
    def __repr__(self) -> str: ...

class Pad(SketchFeature):
    @property
    def height(self) -> float: ...           # depth의 별칭 (기존 API 유지)
    def set_height(self, height, unit=MILLIMETRE) -> None: ...

class Pocket(SketchFeature): ...
```

`PartDesign`은 Pad와 Pocket에 대해 대칭적인 메서드를 갖는다.

```python
.pads     -> list[Pad]          .pockets   -> list[Pocket]
.get_pad(name)                  .get_pocket(name)
.create_pad(name, sketch, height, unit=MILLIMETRE)
.create_pocket(name, sketch, depth, unit=MILLIMETRE)
.ensure_pad(...)                .ensure_pocket(...)
.remove_pad(name)               .remove_pocket(name)
```

`ensure_pocket`의 정책은 `ensure_pad`와 동일하다 (1.3 참조). 기존 `Pad` 공개 signature
(`height`, `set_height`, `create_pad`, `ensure_pad`, `get_pad`, `pads`, `remove_pad`)는
바꾸지 않는다.

### 6.13 Shaft / Groove / Mirror

`parameters/parameter.py`에 각도 지원을 추가한다 (길이 validator와 같은 패턴).

```python
DEGREE: str = "deg"
SUPPORTED_ANGLE_UNITS: frozenset[str] = frozenset({DEGREE})
def validate_angle_unit(unit: str) -> None: ...      # UnsupportedUnitError
def validate_angle_value(value: float) -> float: ... # ParameterTypeError, float 반환
```

`geometry/sketch.py`의 `Sketch`에 축 지정을 추가한다.

```python
def set_center_line(self, line: Any) -> None: ...   # Sketch.CenterLine = line
```

`geometry/part_design.py`:

```python
SHAFT_KIND = "Shaft"; GROOVE_KIND = "Groove"; MIRROR_KIND = "Mirror"
FULL_REVOLUTION: float = 360.0

class RevolvedFeature:          # Shaft/Groove 공통
    com_object, name
    @property first_angle -> float          # FirstAngle.Value, deg
    @property second_angle -> float         # SecondAngle.Value, deg
    def set_first_angle(self, angle: float, unit: str = DEGREE) -> None: ...
    def set_second_angle(self, angle: float, unit: str = DEGREE) -> None: ...
    def sketch(self) -> Sketch: ...
    def first_angle_parameter(self) -> Parameter: ...   # formula 대상
    def __repr__(self) -> str: ...

class Shaft(RevolvedFeature): ...
class Groove(RevolvedFeature): ...

class Mirror:
    com_object, name, __repr__
```

`PartDesign`에 Pad/Pocket과 대칭인 메서드를 추가한다.

```python
.shafts / .get_shaft / .create_shaft(name, sketch)  / .ensure_shaft  / .remove_shaft
.grooves/ .get_groove/ .create_groove(name, sketch) / .ensure_groove / .remove_groove
.mirrors/ .get_mirror/ .create_mirror(name, support=SUPPORT_YZ) / .ensure_mirror
         / .remove_mirror
```

`create_shaft`/`create_groove`는 스케치에 `CenterLine`이 지정돼 있어야 한다. 라이브러리가
미리 확인할 방법이 없으므로 docstring에 요구사항으로 명시하고, 실패는 그대로 전달한다.

`ensure_shaft`/`ensure_groove`의 sketch 비교는 `ensure_pad`와 같다(COM 동일성 `==`).
각도는 `ensure`에서 건드리지 않는다 — 생성 시 기본값(360/0)이고, 바꾸려면
`set_first_angle`을 명시적으로 부른다.

`ensure_mirror`는 support 문자열이 다르면 `FeatureConflictError`를 낸다. Mirror의 평면을
되읽는 방법이 검증되지 않았으므로, 같은 이름이면 support를 비교하지 않고 그대로 재사용하되
그 한계를 docstring에 적는다.

### 6.14 스케치 제약

`geometry/constraint.py` (신규):

```python
CONSTRAINT_HORIZONTAL: int = 10
CONSTRAINT_VERTICAL: int = 13
CONSTRAINT_LENGTH: int = 5
CONSTRAINT_RADIUS: int = 14
CONSTRAINT_PERPENDICULAR: int = 11
CONSTRAINT_PARALLEL: int = 8
CONSTRAINT_DISTANCE: int = 1
CONSTRAINT_COINCIDENT: int = 2
CONSTRAINT_TANGENT: int = 4

class Constraint:
    def __init__(self, com_object: Any) -> None: ...
    @property com_object -> Any
    @property name -> str                  # 'Length.3'
    @property type_code -> int             # Constraint.Type. 요청 코드와 다를 수 있다
    @property status -> int                # 0이 정상
    @property value -> float | None        # Dimension.Value, 치수 제약이 아니면 None
    def set_value(self, value: float, unit: str = MILLIMETRE) -> None: ...
    def dimension_parameter(self) -> Parameter    # formula 대상. 없으면 ParameterTypeError
    def __repr__(self) -> str: ...

class ConstraintCollection:            # 읽기 전용 뷰
    def __init__(self, sketch_com_object: Any) -> None: ...
    @property count -> int
    @property broken_count -> int
    @property unupdated_count -> int
    def list(self) -> "list[Constraint]": ...
    def names(self) -> "list[str]": ...
    def get(self, name: str) -> Constraint: ...   # ConstraintNotFoundError / AmbiguousNameError
    def __len__ / __iter__ / __contains__ / __repr__
```

`Sketch`에 `constraints -> ConstraintCollection` 속성을 추가한다 (최초 접근 시 캐시).

`SketchEditor`에 제약 생성 메서드를 추가한다. **편집 세션 안에서만 유효하므로 여기가 유일하게
올바른 위치다.** 인자는 `line()` / `circle()` 이 돌려준 raw COM 객체를 그대로 받는다.

```python
def horizontal(self, line: Any) -> Constraint: ...
def vertical(self, line: Any) -> Constraint: ...
def perpendicular(self, first: Any, second: Any) -> Constraint: ...
def parallel(self, first: Any, second: Any) -> Constraint: ...
def coincident(self, first: Any, second: Any) -> Constraint: ...
def tangent(self, first: Any, second: Any) -> Constraint: ...
def length(self, line: Any, value: float | None = None,
           unit: str = MILLIMETRE) -> Constraint: ...
def radius(self, circle: Any, value: float | None = None,
           unit: str = MILLIMETRE) -> Constraint: ...
def distance(self, first: Any, second: Any, value: float | None = None,
             unit: str = MILLIMETRE) -> Constraint: ...
```

치수 제약 세 가지는 `value`가 주어지면 생성 직후 `Dimension.Value`에 쓴다. `None`이면 현재
형상에서 잡힌 값을 그대로 둔다.

`SketchEditor`는 제약을 만들 때 `Part.Update()`를 호출하지 않는다.

추가 예외: `ConstraintNotFoundError(Auto3dxError)`.

### 6.15 단위 카탈로그와 Length 외 파라미터 타입

`parameters/units.py` (신규):

```python
@dataclasses.dataclass(frozen=True)
class UnitInfo:
    name: str        # 'Millimeter'
    magnitude: str   # 'Length'
    symbol: str      # 'mm'

class UnitCatalogue:
    """Parameters.Units를 한 번만 열거해 캐시한다 (1887개)."""
    def __init__(self, parameters_com_object: Any) -> None: ...
    def magnitudes(self) -> "list[str]": ...            # 정렬된 339개
    def units(self, magnitude: str) -> "list[UnitInfo]": ...
    def symbols(self, magnitude: str) -> "list[str]": ...
    def supports(self, magnitude: str, symbol: str) -> bool: ...
```

`ParameterCollection`에 `units -> UnitCatalogue` 속성을 추가한다(최초 접근 시 캐시).

`parameters/parameter.py`:

```python
REAL_KIND = "RealParam"; INTEGER_KIND = "IntParam"
STRING_KIND = "StrParam"; BOOLEAN_KIND = "BoolParam"
ANGLE_KIND = "Angle"; DIMENSION_KIND = "Dimension"
DIMENSIONAL_KINDS = frozenset({LENGTH_KIND, ANGLE_KIND, DIMENSION_KIND})

class Parameter:
    @property magnitude -> str | None    # Unit.Magnitude. 무단위면 None
    @property unit -> str | None         # Unit.Symbol. 무단위면 None
```

**`unit`의 기존 동작을 깨지 않는다.** `Unit.Symbol`을 먼저 시도하고, 실패하면 예전처럼
`kind == LENGTH_KIND`일 때 `MILLIMETRE`, 그 외 `None`을 돌려준다. 기존 테스트의 fake에는
`Unit`이 없으므로 이 fallback이 필요하다.

`Parameter.set(value, unit=None)`은 kind로 분기한다.

```text
DIMENSIONAL_KINDS -> 숫자(bool 거부). unit이 주어지면 parameter의 실제 unit과
                     일치해야 한다. 다르면 UnsupportedUnitError.
                     단위 변환은 하지 않는다 (미검증).
                     unit=None 이면 검사 없이 그대로 쓴다.
REAL_KIND         -> int/float(bool 거부) -> float. unit을 주면 UnsupportedUnitError.
INTEGER_KIND      -> int(bool 거부). unit 금지.
STRING_KIND       -> str. unit 금지.
BOOLEAN_KIND      -> bool. unit 금지.
그 외              -> ParameterTypeError
```

기존 호출 `set(150)`과 `set(150, unit="mm")`는 mm Length에서 동일하게 동작해야 한다.

`ParameterCollection`에 생성 메서드를 추가한다. 전부 기존 `create_length`와 같은 안전
장치(이름 검증, 사전 존재 검사, `Part.Update()` 미호출)를 따른다.

```python
.create_real(name, value)     / .ensure_real(name, value)
.create_integer(name, value)  / .ensure_integer(name, value)
.create_string(name, value)   / .ensure_string(name, value)
.create_boolean(name, value)  / .ensure_boolean(name, value)
.create_dimension(name, magnitude, value)   / .ensure_dimension(...)
```

`create_dimension`은 `magnitude`가 `UnitCatalogue.magnitudes()`에 있는지 먼저 확인하고,
없으면 `UnsupportedMagnitudeError`를 낸다(COM 호출 전에). 기존 `create_length`는
`create_dimension(name, "Length", value)`로 구현해도 되지만 **공개 signature는 그대로 둔다.**

`ensure_*`는 이름이 있으면 kind가 맞는지 확인하고(다르면 `ParameterTypeError`) 값을 쓴다.

추가 예외: `UnsupportedMagnitudeError(Auto3dxError)`.

### 6.16 Rib

```python
RIB_KIND: str = "Rib"

class Rib:
    com_object, name
    def profile(self) -> Sketch: ...       # Rib.Sketch
    def __repr__(self) -> str: ...

# PartDesign
.ribs -> list[Rib]   .get_rib(name)
.create_rib(name, profile: Sketch, path: Sketch) -> Rib
.ensure_rib(name, profile: Sketch, path: Sketch) -> Rib
.remove_rib(name)
```

`ensure_rib`의 충돌 판정은 `ensure_pad`와 같이 **프로파일 스케치의 COM 동일성(`==`)** 으로
한다. 경로 스케치를 되읽는 방법은 검증되지 않았으므로 비교하지 않으며, 그 한계를 docstring에
적는다.

Stiffener, Slot, Pattern은 미검증이므로 구현하지 않는다.

### 6.12 `auto_3dx/formulas/`

```python
# formulas/formula.py
class Formula:
    def __init__(self, com_object: Any) -> None: ...
    @property
    def com_object(self) -> Any: ...
    @property
    def name(self) -> str: ...
    @property
    def body(self) -> str: ...               # Formula.Value = 수식 본문
    @property
    def comment(self) -> str: ...
    @property
    def activated(self) -> bool: ...
    @property
    def input_count(self) -> int: ...        # NbInParameters
    def modify(self, body: str) -> None: ...
    def rename(self, name: str) -> None: ...
    def activate(self) -> None: ...
    def deactivate(self) -> None: ...
    def __repr__(self) -> str: ...

# formulas/collection.py
class FormulaCollection:
    def __init__(self, part_com_object: Any) -> None: ...   # Part.Relations + Part.Parameters
    @property
    def count(self) -> int: ...
    def list(self) -> list[Formula]: ...
    def names(self) -> "list[str]": ...
    def get(self, name: str) -> Formula: ...
    def relation_name(self, parameter: Parameter) -> str: ...
    def create(self, name: str, target: Parameter, body: str,
               comment: str = "") -> Formula: ...
    def ensure(self, name: str, target: Parameter, body: str,
               comment: str = "") -> Formula: ...
    def remove(self, name: str) -> None: ...
    def __len__(self) -> int: ...
    def __iter__(self) -> Iterator[Formula]: ...
    def __contains__(self, name: object) -> bool: ...
```

`Part`가 `part.formulas -> FormulaCollection`을 추가로 노출한다 (최초 접근 시 캐시).

`relation_name()`은 `Parameters.GetNameToUseInRelation`을 감싼다. **수식 본문을 만들 때
`Parameter.name`을 쓰면 안 되고 이것을 써야 한다.** 1.2.1의 실측 참조.

`ensure` 정책:

```text
이름 2개 이상            -> AmbiguousNameError
이름 없음                -> 생성
이름 있음 + 본문 같음     -> 그대로 재사용
이름 있음 + 본문 다름     -> Modify(body)로 갱신
```

`create`/`ensure`/`modify`는 `Part.Update()`를 호출하지 않는다.

추가 예외: `FormulaNotFoundError(Auto3dxError)`, `FormulaAlreadyExistsError(Auto3dxError)`.

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
