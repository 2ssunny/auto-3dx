# auto-3dx Module & API Conventions

> **Contributor reference, written in Korean.** This is the measured COM evidence log and
> the coding conventions the implementation follows; the source code cites its sections.
> It is not user documentation. The canonical description of the 1.0.0 public API is
> [`docs/v1.0.0.md`](v1.0.0.md), and the architecture contract is
> [`docs/api-design.md`](api-design.md), whose Appendix A carries the newer probe evidence.
> Where this log records an earlier limitation that 1.0.0 has since resolved, a note says so.

이 문서는 `auto-3dx` 라이브러리 코드를 작성할 때 따르는 규칙과, 첫 번째 수직 기능
("실행 중인 Part의 기존 Length Parameter 수정 + update")부터 축적한 실측 기록을 정의한다.
아래 첫 표는 초기 단계의 검증 범위이며 현재 지원 범위가 아니다. 이후 절의 추가 실측과
현재 공개 API 상태는 `docs/v1.0.0.md` 및 `docs/api-design.md`를 따른다.

여러 작업자가 병렬로 구현하더라도 이 문서의 signature를 그대로 구현하면 서로 맞물린다.

---

## 1. 검증된 사실 (Ground truth)

추측 금지. 아래는 B428_Cloud 설치본에서 초기 단계에 실제 COM 호출로 확인한 내용이다.
이 초기 목록에 없는 동작은 해당 단계에서는 미검증이었다. 이후 절에서 검증한 동작은
현재 공개 API에 포함될 수 있다.

### 환경

```text
Release        : B428_Cloud
com3dx.py      : <code>\python3dx\lib\com3dx.py  (CATIA.Application 레지스트리에서 발견)
Python         : 표준 CPython 3.14.2 venv, pywin32 312   (live 검증, 2026-09-15)
                 Conda env auto-3dx, Python 3.11.16, pywin32 312   (live 검증, 2026-09-15)
                 Anaconda base 3.13.9, pywin32 311, PYTHONPATH=src (개발 중 live 실행)
                 모두 64-bit. 이 절의 COM 사실 대부분은 Conda 3.11.16에서 처음 측정했다
```

COM 동작은 Python 배포판과 무관하다. `com3dx`는 pywin32의 `gencache`로 Python 버전별
wrapper cache(`%TEMP%\gen_py\3.11`, `...\3.14`)를 만들고, 새 인터프리터에서 처음 연결하면
"Checking cache ..."를 출력하며 cache를 새로 만든 뒤 연결한다. 표준 CPython venv와 Conda의
live 통합 테스트 결과와 실행 뒤 모델 상태가 같았다.

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

### 초기 단계에서 검증된 동작 (역사적 기록)

| 동작 | 상태 |
|---|---|
| `attach_running_application()` | 검증 완료 |
| `ActiveEditor` / `ActiveObject` 조회 | 검증 완료 |
| Part / Assembly context 구분 | 검증 완료 |
| `Parameters.Count`, `Item(i)`, `Item(name)` | 검증 완료 |
| `Length.Value` 읽기 / 쓰기 | 검증 완료 |
| `Part.Update()` | 검증 완료 |
| Length parameter 생성 / ensure / remove | 검증 완료 (아래 1.1) |
| 그 외 Parameter 생성 (`CreateReal` 등) | 당시 미검증; 현재 상태는 `docs/v1.0.0.md` 참조 |
| Formula / Relations | 당시 미검증; 현재 상태는 `docs/v1.0.0.md` 참조 |
| Sketch / Pad / GSD | 당시 미검증; 현재 상태는 `docs/v1.0.0.md` 참조 |
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

**`Sketch`에는 support/plane 속성이 없다.** 2026-09-16에 live 객체의 멤버를 다시 확인해도
`Support`/`Plane`/`Reference`는 없고 `Parent`는 `Sketches` 컬렉션이다. 어느 평면에 붙었는지는
`GetAbsoluteAxisData`로만 알 수 있고, 실측값은 support마다 다음과 같이 구분된다
(origin 3 + X방향 3 + Y방향 3). 사용자 정의 평면 위의 스케치는 1.7절 방식으로 판정한다:

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

**당시 미검증:** `Constraints.Remove(i)`는 이 단계에서 호출해 보지 않았다.
이후 스케치 제약 삭제를 검증·구현했다(`docs/api-design.md` 18절).

### 1.2.7 사용자 정의 평면 (실측, probes 29·33·36)

이 실측 단계에서는 원점 평면 3개(XY/YZ/ZX)에만 스케치를 만들 수 있었다.
이후 offset/각도 평면(이 절)과, Phase 5에서 평면 Face support(1.14, `docs/api-design.md`
20절)를 검증·구현했다.

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

**pad가 실패하던 원인은 평면이 아니라 in-work object였다 (probe 36).**

```text
HybridBodies.Add()  -> 새 기하 세트가 Part의 in-work object가 된다
pad는 기하 세트에 들어갈 수 없으므로 AddNewPad가 거부된다
Part.InWorkObject = MainBody 로 되돌리면 통과한다
```

기하 세트에 무언가 추가할 때마다 in-work object가 다시 바뀌므로, **`AppendHybridShape` 뒤에는
매번 body를 되찾아야 한다.** 이걸 놓치면 평면과 무관한 지점에서 COM 오류가 난다.

**각도 평면은 회전축이 주소 지정 가능한 3D 선이어야 한다 (probe 36).**

```text
회전축 = 스케치 안의 Line2D  -> 생성은 되나 update 실패 (probe 29)
회전축 = 원점 평면           -> 생성은 되나 update 실패
회전축 = AddNewLinePtPt(점, 점) -> 생성 + update 성공 -> 검증됨
```

```text
AddNewPointCoord(iX, iY, iZ)                            -> HybridShapePointCoord
AddNewLinePtPt(iPtOrigine, iPtExtremite)                -> HybridShapeLinePtPt
AddNewPlaneAngle(iPlane, iRevolAxis, iAngle, iOrientation) -> HybridShapePlaneAngle
```

이제 **offset 평면과 각도 평면 모두** 평면 -> 스케치 -> pad 전 단계에서 update가 성공한다.
되읽기는 `Offset.Value`, `Angle.Value`, `Plane.DisplayName`이 동작한다.

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

현재 wrapper 계약은 다음과 같다.

```python
with sketch.edit() as editor:
    arc = editor.arc(cx, cy, radius, start_param, end_param)  # 열린 Circle2D
    spline = editor.spline([(x1, y1), (x2, y2), (x3, y3)])    # Spline2D
    editor.set_construction(arc, True)
```

`arc()`의 start/end parameter 단위는 아직 확정하지 않았으므로 opaque 값으로 취급한다.
`spline()`은 좌표 목록을 받아 내부에서 `ControlPoint2D`를 만들며, 최소 점 개수는 미확정이다.
세 메서드는 `Sketch.edit()` 안에서만 사용하고 `Part.Update()`는 호출하지 않는다.

서로 다른 두 `Circle2D`에는 `editor.concentric(first, second)`로 동심 제약을 걸 수 있다.
이 경로도 편집 세션 안에서만 유효하며, 생성 시 `CONSTRAINT_CONCENTRICITY == 3`을 사용한다.

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

이 기준으로 Stiffener는 **미검증**이며 구현하지 않는다. Rectangular Pattern은 이후
probe 26·30에서 올바른 방향 Reference 조합으로 생성과 `Part.Update()`까지 검증됐고,
계약은 1.2.5와 6.17에 기록한다.

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
모서리를 요구한다. chamfer도 모서리를 받으며, 인자는 아래에서 확정했다.

**첫 fillet 이후 모든 시도가 update에서 실패한 원인은 두 가지가 겹친 것이었다** (probes 34·35).

신선한 검색으로 fillet 3개를 연달아 만들면 전부 통과한다. probe 34에서는 같은 검색 결과로
2개를 만들어도 통과했는데, **그건 우연이었다.** 평면 pad 하나에 fillet을 걸고 나서 같은
snapshot으로 두 번째를 만들면 다음 모서리·중간 모서리·마지막 모서리 **전부 실패한다**(둘은
생성 단계에서, 하나는 update에서). 새 snapshot의 첫 모서리는 성공한다.

즉 **수정 후 기존 Reference가 통할지는 예측할 수 없다.** 그 모서리가 변경을 그대로 견뎠는지에
달려 있고 호출자는 그걸 알 수 없다. 그래서 라이브러리는 `PartDesign`이 모델을 바꾸는 순간
기존 snapshot을 stale로 표시하고, 이후 사용은 COM에 닿기 전에 `StaleSnapshotError`로
거부한다. 되는지 안 되는지 모르는 호출을 그대로 내보내지 않는다.

**실제 원인: update가 한 번 실패하면 그 feature를 지우기 전까지 이후 update가 전부 실패한다.**
probe 28은 update가 실패한 chamfer를 트리에 남긴 채 다음으로 넘어갔다. 따라서 `create_*` 뒤
update가 실패하면 호출자는 **반드시 그 feature를 지워야** 하고, 지우지 않고 이어가면 무관한
실패가 줄줄이 따라온다.

**어느 모서리인지 재빌드를 넘어 지목하는 방법은 없다.** 네 경로가 모두 막혔다.

```text
BRep 이름 저장 후 재해석   : CreateReferenceFromBRepName -> Part·Pad context 모두 실패
재빌드 후 이름·순서 보존   : pad 높이 하나 바꾸니 edge 20 -> 29개,
                             이름 multiset과 검색 순서 둘 다 달라짐
측정으로 기하 선택         : MeasurableService가 edge GetLength를 노출하지 않음
검색 범위를 feature로 한정 : 'Topology.Edge,in,<이름>' 계열은 전부 COM 오류.
                             'Topology.Edge,in'은 all과 동일(솔리드 전체)
```

**모델이 바뀌지 않는 동안에는** 검색이 정확히 재현된다(개수·이름·순서 모두 동일, 2회 확인).
따라서 index는 **그 시점의 모델 상태에서만** 의미가 있다. 수정이 일어나면 개수부터 변한다
(fillet을 걸수록 29 -> 32 -> 38 -> 41). API는 이 한계를 숨기지 말고 드러내야 한다.

#### chamfer 인자 (실측, probe 35)

type library에 enum 메타데이터가 없어(순수 `VT_I4`) 정수 3개의 의미를 몰랐다. 시도마다
chamfer를 지워 깨끗한 상태에서 다시 시작하며 조합을 훑었다.

```text
AddNewChamfer(iObjectToChamfer, iPropagation, iMode, iOrientation,
              iLength1, iLength2OrAngle) -> Chamfer

mode=0  -> 생성은 되나 update 실패
mode=1  -> 생성 + update 성공     (propagation 0·1, orientation 0·1 모두)
mode=2  -> 생성 자체가 실패
```

**mode는 1이어야 한다.** 다른 값은 제공하지 않는다.

#### 면을 받는 feature (실측, probe 37)

fillet과 chamfer가 면 Reference를 거부한 것은 **그 둘이 모서리를 원하기 때문**이지 면 참조가
안 되기 때문이 아니었다. 진짜 면을 받는 feature 세 개를 처음 시험했고 **전부 첫 면에서**
생성과 `Part.Update()`가 통과했다.

```text
AddNewShell(iFaceToRemove, iInternalThickness, iExternalThickness) -> Shell
  실측 (면, 2.0, 0.0)
AddNewThickness(iFaceToThicken, iOffset)                           -> Thickness
  실측 (면, 3.0)
AddNewHole(iSupport, iDepth)                                       -> Hole
  실측 (면, 5.0)
```

면 참조를 얻는 경로는 모서리와 같다. `Search('Topology.Face,all')` 후
`SelectedElement.Reference`다. 40x40x20 pad에서 면 8개가 나왔다.

따라서 1.2.2의 "참조 레이어가 없어 막힌" 목록 중 shell·thickness·hole이 풀렸다. 남은 것은
draft 계열처럼 인자가 더 많은 feature들이다.

### 1.2.5 Rib / Stiffener / Pattern (실측, probes 24·26·30)

```text
AddNewRib(iSketch, iCenterCurve)  -> Rib       생성 + Update 성공 -> 검증됨
AddNewSlot(iSketch, iCenterCurve) -> Slot      생성 + Update 성공 -> 검증됨
AddNewStiffener(iSketch)          -> Stiffener 생성은 되나 Update 실패 (2회) -> 미검증
AddNewRectPattern(...)                         생성 + Update 성공 조합 검증 (아래)
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

공개 API는 평면이 아니라 **축**으로 말한다(`"X"`, `"-X"`, ...). 평면을 인자로 받으면
검증할 수 없는 대응 관계의 책임을 호출자에게 떠넘기게 된다. 현재 wrapper는 이 축을
검증된 원점 평면 Reference와 reverse flag 조합으로 변환한다.

`PartDesign`에는 `create_rectangular_pattern()` public API가 구현되어 있고 방향·개수·간격
검사를 unit 테스트로 고정했다. 공개 adapter의 생성 → `Part.Update()` → Selection cleanup
live integration도 통과했으며, 방향 매핑의 최초 live 근거는 probe 26·30이다.

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

**`InertiaBoxService`는 구현하지 않는다. 세션에 따라 조용히 0을 돌려준다.**

`GetBoundingBox`는 인자 없이 호출하면 type mismatch고, 3개짜리 시퀀스 2개를 넘기면
반환값으로 `(origin, lengths)`를 돌려준다(인자를 바꾸는 방식이 아니다). 한 세션에서는 이렇게
호출해 블록의 실제 값 `(60, 40, 12) mm`를 얻었다. **그런데 바뀌지 않은 같은 모델에서 다른
세션에서는 전부 0이 나왔다.** 같은 호출에서 부피와 무게중심은 그대로 정확했다.

가능한 호출 형태를 전부 시도했고 모두 0이었다.

```text
tuple seed / list seed / 9개 seed / raw MainBody / Reference / Pad / Part 자체
GetInertiaElement로 먼저 priming / OnlyMainBody() 호출 후
```

**예외도 아니고 0을 돌려주는 측정은 없는 것보다 위험하다.** 호출자가 0을 정상값으로 읽는다.
게다가 이 상자는 축 정렬이 아니라 솔리드의 **주관성축** 정렬이다. 단순한 블록에서는 전역 축과
일치해서 쓸 만해 보이는데 그게 바로 함정이고, 형상이 비대칭이 되면 상자가 회전한다. 패턴
하나를 걸었더니 세 축이 동시에 늘어난 것으로 나왔다. 동작할 때조차 "X 방향으로 얼마나 큰가"에
답할 수 없으므로, 공개 API에서 제외했다.

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

### 1.5 검사·selection 복원·export (실측, 2026-09-15, probes 38·39)

검사에 쓸 읽기가 live로 확인됐다.

```text
Part.Bodies.Count / Item(i) / Name          -> 동작. Item(1) == MainBody -> True
같은 Body를 두 번 읽어 ==                   -> True (Body COM 동일성)
Body.Shapes / Sketches의 Count·Item·Name    -> 동작
HybridBodies.Item(i).HybridShapes.Count     -> 동작 (임시 offset 평면 1개로 확인)
HybridShapes.Item(i).Name / type 이름        -> AUTO3DX_P38_PLANE / HybridShapePlaneOffset
HybridBody.HybridBodies.Count (중첩 세트)   -> 동작 (0)
Part.IsUpToDate(Part)                      -> Python bool
Topology.Edge / Face 검색 2회              -> 16/16, 6/6 일치
```

**Part의 COM 동일성도 확인됐다.** `active_part()`를 두 번 읽은 COM 객체는 `==`로 같고 `is`로는
다르다. `part_named(같은 이름)`도 같고, 다른 열린 Part와는 다르다.

**비어 있지 않은 selection 복원이 된다.** 기준 pad와 기준 스케치를 선택한 상태에서 topology
검색을 돌리면 selection이 바뀐다. 검색 전에 `Selection.Item(i).Value`로 캡처하고, 끝나면
`Clear()` 후 캡처한 값마다 `Add()`하면 두 항목이 순서, 이름, 타입 모두 그대로 돌아왔다. 다른
프로세스에서 읽어도 복원된 selection이 보였다.

추가 실측(같은 날, selection만 건드림):

```text
Search("Topology.Face,all")로 남은 PlanarFace 6개 -> 캡처·복원 6/6, 순서·이름·타입 일치
Selection.Add(검색으로 얻은 Reference)            -> 예외 없이 무시됨 (Count 변화 없음)
Search(면) 직후 Add(그 면들을 가진 Pad)            -> 7개가 됨
그 7개를 캡처해 복원: 면 6개 Add 뒤 Add(Pad)        -> 예외 없이 무시됨 (6 -> 6)
Add(Pad) 뒤 Search(면)                            -> Search가 selection을 바꿔 6개
```

`Add`가 예외 없이 무시될 수 있으므로 복원은 `Count`를 다시 읽어 확인한다. 이 경우 selection은
이미 바뀌었으므로 스냅샷은 돌려주고 `SelectionNotRestoredWarning`으로 알린다(api-design 7절).

**In-Work Object 읽기와 SDK 작업에 따른 변화 (실측, 2026-09-15).** `Part.InWorkObject`의 `Name`,
타입 이름, `== MainBody`를 SDK 작업 단계마다 읽었다.

```text
시작, 두 번째 읽기           AUTO3DX_BASE_PAD  Pad   main=False
sketches.create / edit / update  변화 없음
create_pad + update           새 pad           Pad   main=False
planes.create_offset          PartBody          Body  main=True   (geometry.planes가 되찾음)
정리(세트·pad·스케치 삭제) + update  PartBody    Body  main=True   (이전 값으로 돌아가지 않음)
InWorkObject = 원래 객체       AUTO3DX_BASE_PAD  Pad   main=False
```

이 읽기로 `part.inspect.in_work_object()`를 만들었다. 통합 테스트 세션은 In-Work Object도
시작 시 저장하고 끝날 때 되돌린다(`tests/integration/conftest.py`).

### 1.6 평면 재발견 (실측, 2026-09-16)

`PlaneCollection`이 만든 기하 세트를 인스턴스에 들고 있었기 때문에, 파이썬 프로세스가
끝나면 그 안의 평면을 찾지도 지우지도 못했다. 이제 매번 모델에서 찾는다.

```text
Part.HybridBodies.Count / Item(i).Name        -> 동작 (auto_3dx_Planes 찾기)
HybridBody.HybridShapes.Count / Item(i).Name  -> 동작
type(HybridShapes.Item(i)).__name__           -> HybridShapePlaneOffset / HybridShapePlaneAngle
                                                 HybridShapePointCoord / HybridShapeLinePtPt
```

`create_angle`이 만드는 축 점 2개와 축 선도 같은 세트에 있으므로, 평면만 돌려주도록
타입 이름으로 거른다. offset 평면은 `OffsetPlane`, 각도 평면은 `AnglePlane`으로 감싸고
`Offset.Value`(40.0)와 `Angle.Value`(30.0)를 그대로 읽었다.

**별도 프로세스 검증 (A/B/C, 공개 API만 사용).**

```text
A: create_offset("AUTO3DX_LIFECYCLE_PLANE", "XY", 40) + update -> names() ['AUTO3DX_LIFECYCLE_PLANE']
   정리하지 않고 종료
B: 새 인터프리터로 attach -> names()에서 A의 평면 발견, get()으로 offset 40.0,
   base_display_name 'xy plane' -> remove(plane) -> remove_geometrical_set() -> update
   -> names() [] , get()은 PlaneNotFoundError
C: 새 인터프리터로 inspect -> 기하 세트 0개, 평면 0개, feature/스케치/파라미터/부피/
   In-Work Object가 A 이전 기준과 같음
```

세 프로세스 모두 저장·propagate·export를 하지 않았고 raw COM도 쓰지 않았다.

**export는 이 설치본에서 쓸 수 없다.** 유일한 Automation 경로는
`Application.Documents`에서 `PartDocument.Part == Part`로 문서를 찾아
`PartDocument.ExportData(path, format)`을 부르는 것이다. `Documents`에는 CATPCCModel
`Document` 하나와 열린 Part마다 `PartDocument`가 하나씩 있었다. 활성 Part의 문서는 PLM 기반이라
`Path`가 비어 있고 `FullName`이 불투명한 ID다.

```text
ExportData(path, "stp") -> HRESULT 0x80020009, 내부 0x80004005 (E_FAIL), 설명 없음
ExportData(path, "stl") -> 같은 실패
파일 생성 없음 / Saved 전후 False 그대로 / 모델 변화 없음
```

시도 뒤에 활성 객체를 읽을 수 없는 editor(`CATIAEditor36`)가 새로 생겼다. 원인을 확실히 가리지
못했으므로 export 시도는 반복하지 않는다.

### 1.7 스케치 support 판정 (실측, 2026-09-16)

사용자 정의 평면 위에 만든 스케치는 `support()`가 `None`이었다. 원점 평면 3개의 기준 프레임과만
비교했기 때문이다. 평면 쪽이 자기 프레임을 알려준다는 것이 확인되어 이제 프레임을 맞춰 본다.

```text
plane.IsARefPlane()          -> 1
plane.GetOrigin([0,0,0])     -> (0.0, 0.0, 35.0)      # 3개짜리 seed 필요, 인자 없으면 Type mismatch
plane.GetFirstAxis([0,0,0])  -> (1.0, 0.0, 0.0)
plane.GetSecondAxis([0,0,0]) -> (0.0, 1.0, 0.0)
sketch.GetAbsoluteAxisData   -> (0,0,35, 1,0,0, 0,1,0)   # 평면 프레임과 완전히 같음
```

각도 평면(30도)에서도 같았다: 평면 `(0,0,0)/(0,1,0)/(-0.8660254037844386,0,0.5)`,
스케치 `(0,0,0, 0,1,0, -0.866...,0,0.5)`. 축에 정렬되지 않은 프레임까지 그대로 일치하므로
기하 추정이 아니라 **동등 비교**로 판정한다. 프레임이 같은 평면이 둘이면 고르지 않고 `None`이다.

**원점 평면은 이 방법을 못 쓴다.** `OriginElements.PlaneXY`는 이 릴리스에서 `AnyObject`로 오고
`GetOrigin`/`GetFirstAxis`/`GetSecondAxis`/`IsARefPlane`이 전부 `AttributeError`다. 그래서
원점 3개는 검증된 상수 프레임으로 먼저 판정하고, 그다음에 `part.planes`의 평면과 비교한다.

`MeasurableService`도 시도했다. `GetService("MeasurableService")`는 응답하지만
`GetMeasurable(reference)`가 `Parameter not optional`로 실패했다. 평면 프레임 경로가 이미
있으므로 더 파지 않았고, 이 서비스는 여전히 미검증이다.

**평면을 만든 뒤에는 `Part.Update()`를 먼저 불러야 그 평면에 스케치를 만들 수 있다.** update 없이
`sketches.create(support=plane)`를 부르면 `Sketches.Add`가 `The method Add failed`(0x80004005)로
거부한다. 기존 live 테스트가 평면 생성 뒤 update를 부르고 있어 그동안 드러나지 않았다.

### 1.8 Multi-sections Solid (probe 40, 실측 2026-09-17)

타입 라이브러리에서 확인한 시그니처:

```text
ShapeFactory.AddNewLoft() -> Loft                         (인자 없음)
Loft: Name (r/w), HybridShape -> HybridShape, Parent, GetItem
HybridShapeLoft.AddSectionToLoft(iCrv, iOri, iPoint)
HybridShapeLoft.GetSectionFromLoft(iRank, oCrv, oOri, oPoint)
HybridShapeLoft.RemoveSection(iSection), GetNbOfGuides()  -- 섹션 개수 멤버는 없다
```

live 결과 (공개 API로 XY의 40x20 사각형 스케치, +30mm offset 평면, 그 위 30x15 사각형 스케치를
만든 뒤 Loft만 raw로 호출):

```text
AddNewLoft()                         -> type 'Loft', 기본 이름 'Multi-sections Solid.1'
In-Work Object                       -> PartBody에서 HybridShapeLoft 'Multi-sections Solid.1'로 바뀜
loft.HybridShape                     -> HybridShapeLoft
CreateReferenceFromObject(sketch)    -> Reference
AddSectionToLoft(reference, 1, None) -> 예외 없음 (두 섹션 모두)
loft.Name = 'AUTO3DX_P40_LOFT'       -> 동작
Part.Update()                        -> 실패 (E_FAIL)  <- 사각형 두 개로는 solid가 만들어지지 않았다
MainBody.Shapes.Item(i)              -> type 'Loft', 바뀐 이름으로 다시 찾음
Shapes 항목 == AddNewLoft 반환 객체    -> False   (COM 동일성으로 같은 feature를 판정할 수 없다)
GetSectionFromLoft(0)                -> 실패 E_FAIL
GetSectionFromLoft(1) / (2)          -> (Reference, 1, None), Reference.DisplayName == 스케치 이름
                                        Reference == Sketch 객체 -> False
GetSectionFromLoft(3)                -> 실패 E_FAIL (섹션 2개일 때 마지막 다음 순위)
Selection으로 Loft 삭제                -> 섹션 스케치 두 개도 함께 삭제됨 (Pad가 스케치를 지우는 것과 같다)
```

그 전에 사용자가 raw로 같은 경로(`AddNewLoft` + `AddSectionToLoft(reference, 1, None)` 두 번 +
`Part.Update()`)를 돌려 NACA 2415(root, chord 150mm, XY)와 NACA 2412(tip, chord 100mm, +300mm)
사이의 날개 solid를 만들고 측정까지 했다. SDK로는 아직 재현하지 않았다.

이 사실로 `part_design.create_multi_section_solid`/`get_`/`remove_`/`multi_section_solids`와
`MultiSectionSolid.section_names()`를 만들었다.

- 섹션은 스케치에서 만든 `Reference`로 넘기고 `iOri`는 1, 닫힘점은 `None`이다. 시도한 조합이 이것뿐이다.
- 섹션 개수 멤버가 없으므로 `section_names()`는 1순위부터 읽다가 **E_FAIL**이 나오면 멈춘다. 다른
  오류는 끝으로 보지 않고 그대로 올린다. 이름은 `Reference.DisplayName`이다.
- feature를 찾는 것은 이름과 타입(`Loft`)으로 한다. COM 동일성은 위에서처럼 믿을 수 없다.
- In-Work Object가 Loft의 `HybridShape`로 바뀌는 것은 그대로 둔다. 되돌리지 않는다.

**공개 API live 검증 (2026-09-17, 표준 CPython 3.14.2, Part `3D Shape00422533`).**

사용자가 raw로 만든 날개가 들어 있는 Part에서 돌렸다. 그 날개는 읽기만 했고, 검증이 만든 것만
지웠으며, 평면 생성이 옮긴 In-Work Object는 매번 원래 값으로 되돌렸다. 모든 실행 뒤 전체 Part
(In-Work Object와 selection 포함)가 실행 전 기준과 같았다.

```text
사용자의 raw 날개를 새 프로세스에서 SDK로 읽기(읽기 전용)
  get_multi_section_solid('WING_SOLID_LOFT')     -> kind Loft, supported
  section_names()                                -> ['WING_ROOT_NACA2415', 'WING_TIP_NACA2412']
  두 섹션 스케치의 support()                        -> 'XY' / OffsetPlane('WING_TIP_PLANE', 300.0)
  부피 449699.966 mm3, 면적 80076.347 mm2
  섹션 구성                                       -> 스케치마다 닫힌 Spline2D 하나, 제어점 49개,
                                                   시작점 = 끝점 = 날카로운 뒷전, 제약 0개

섹션 모양별 Part.Update() (AddSectionToLoft(reference, 1, None), 닫힘점 없음)
  사각형 40x20 -> 30x15                  실패 (probe 40, acceptance, 통합 테스트 세 번)
  NACA, 열린 뒷전 spline + 선            실패
  원 R20 -> R12                          성공
  NACA, 닫힌 spline 하나                  성공
```

즉 모서리가 있는 섹션은 닫힘점 없이는 만들어지지 않았고, 모서리 없는 섹션은 만들어졌다. 닫힘점을
설정하는 API는 범위 밖이므로 원인을 닫힘점으로 확정하지는 않았고, 관찰된 규칙으로만 기록한다.

```text
원 두 개 (통합 테스트, 새 wrapper에서 재발견)
  update, kind Loft, topology 변화, 부피 증가 = 원뿔대 부피 +-1%
  section_names() == [root, tip], 삭제하면 섹션 스케치도 사라짐
사각형 두 개 (통합 테스트)
  update -> PartUpdateError, is_up_to_date False
  remove_multi_section_solid -> update 성공, is_up_to_date True
원 두 개 수명 주기 (scripts/acceptance/multi_section_solid_lifecycle.py create circle / verify-and-remove)
  프로세스 A: 생성, update, 검증 후 정리 없이 종료
  프로세스 B: get_multi_section_solid로 재발견, section_names 확인, 삭제, 기준 복원
NACA 날개 (scripts/acceptance/naca_wing_multi_section_solid.py create / verify / remove, 공개 API만)
  root NACA 2415 chord 150 (XY), tip NACA 2412 chord 100 (+300mm 평면), X로 400mm 옮김
  A: update 성공, 부피 +449702.881 mm3 (raw 날개 449699.966), 면적 +80076.4, topology 8/4 -> 16/8
  B: 새 프로세스에서 root/tip 스케치·tip 평면·날개를 이름으로 찾음, section_names, is_up_to_date,
     topology, 부피, 면적, 무게중심 x 253.95 (두 날개 중간)
  C: 새 프로세스에서 삭제, 기준 복원
```

**B에서 드러난 한계.** 사용자의 `WING_TIP_PLANE`과 검증용 평면이 둘 다 XY에서 +300mm라 프레임이
같았고, 검증용 tip 스케치의 `support()`는 설계대로 `None`이었다(1.7). 스케치에 support 멤버가 없으니
프레임이 같은 평면은 구분할 수 없다.

**`part.planes`와 In-Work Object.** 섹션 스케치를 위한 평면을 만들면 `geometry.planes`가 In-Work
Object를 main body로 되찾는다. Loft가 In-Work Object였던 Part라면 그 값이 바뀐다. 통합 테스트
세션은 끝날 때 되돌리고, 수동 검증에서는 되돌리는 단계를 따로 뒀다.

지원하지 않는 것: guide 곡선, spine, 닫힘점, coupling 설정, tangency, relimitation, Multi-Section
Surface(GSD loft).

**사고 기록.** probe 40의 첫 실행은 활성 Part가 테스트 Part가 아니었는데 그대로 돌았고, 정리 단계의
`remove_geometrical_set()`이 `auto_3dx_Planes` 세트를 통째로 지워 다른 작업의 `GEAR_TOP_PLANE`을
삭제했다. 그 평면 위의 스케치가 support를 잃어 `Part.Update()`가 실패하는 상태가 됐다(저장은 없음).
이후 probe와 acceptance 스크립트는 `AUTO3DX_LIVE_PART`로 이름을 지정한 Part에서만 돌고, 자기가 만든
평면 하나만 지운다. live 통합 테스트 세션도 같은 환경 변수가 활성 Part와 일치해야만 시작한다.

### 1.9 Multi-Body와 활성 Part 가드 (probe 41, 실측 2026-09-17)

모든 live 실행은 사용자가 연 빈 테스트 Part `AUTO3DX_MULTIBODY_TEST`에서만 했다.

**Part 이름.** 이 Part의 Automation `Part.Name`은 `3D Shape00422557`이고, 3DEXPERIENCE 제목
`AUTO3DX_MULTIBODY_TEST`는 `Application.ActiveWindow.Caption`으로만 읽혔다. 그래서 통합 테스트 세션,
probe, acceptance 스크립트는 `AUTO3DX_LIVE_PART`가 활성 Part의 `Part.Name` **또는** 활성 창 제목과
같을 때만 돈다. 창 제목은 활성 Part에만 쓸 수 있다.

**비활성 Part의 `Selection.Search`.** 열린 Part 다섯 개에서 각자 editor의 Selection으로
`Topology.Edge,all`/`Topology.Face,all`을 검색했더니 모두 활성 Part의 개수(모서리 198, 면 53)를
돌려줬다. 측정 service는 editor마다 맞는 값을 줬다. 즉 비활성 Part에 대한 Selection 기반 검색은
다른 Part를 가리키고, 같은 경로의 삭제도 안전하다고 볼 수 없다.

```text
Part.Application.ActiveEditor.ActiveObject == Part   -> 활성 Part에서만 True (세 번 연속 읽기)
ActiveEditor.Selection == 그 editor의 selection      -> 활성 Part에서도 False, 판정에 못 씀
```

이 사실로 `geometry.deletion.require_active_part`를 만들었다. Selection을 거치는 모든 동작
(`remove_*` 삭제, `part.topology` 검색, body 표시/숨김, `bodies.remove`)이 COM을 건드리기 전에
`ActiveEditor.ActiveObject`가 대상 Part인지 확인하고, 아니거나 확인할 수 없으면
`InactivePartError`(`SessionError`)로 거부한다. `part.inspect.topology()`는 이 경우 틀린 숫자 대신
`None`을 돌려준다. 검증된 per-editor 경로가 생길 때까지 유지한다.

**Body (probe 41).**

```text
Part.Bodies.Add()                    -> Body, 기본 이름 'Body.N', 새 body가 In-Work Object가 됨
body.Name = 'X'                      -> 동작, Bodies.Item(i) == Add 반환 객체 -> True
Part.InWorkObject = body             -> 동작, 읽으면 그 body
body.Sketches.Add(plane)             -> 그 body에 들어감
MainBody.Sketches.Add(plane)         -> 다른 body가 In-Work여도 PartBody에 들어감
ShapeFactory.AddNewPad / AddNewPocket -> In-Work Object인 body에 들어가고, 새 feature가 In-Work Object가 됨
body.InBooleanOperation              -> False
body.HybridBodies                    -> 기하 세트가 없는 body에서는 None (Count를 읽으면 AttributeError)
Selection.Add(body); VisProperties.GetShow()  -> (0, state), 0 = 보임, 1 = 숨김
VisProperties.SetShow(1)             -> 숨김. 다시 선택해 읽어도 1, 다른 body는 영향 없음
VisProperties.SetShow(0)             -> 다시 보임, 부피 그대로
Selection으로 body 삭제                -> body와 그 안의 feature, 스케치가 함께 사라짐
빈 body나 숨긴 body 측정               -> GetArea E_FAIL (AutomationError)
```

이 사실로 `part.bodies`(`list`/`names`/`get`/`main`/`create`/`remove`)와 `Body`
(`name`/`is_main`/`features`/`sketch_names`/`is_visible`/`hide()`/`show()`), `part.work_in(body)`를
만들었다.

- **body 찾기**는 이름으로, main body 판정은 `MainBody`와의 COM 동일성으로 한다.
- **`bodies.create`**는 `Bodies.Add`가 옮긴 In-Work Object를 원래 값으로 되돌린다. 이름을 붙이지
  못하면 `PartialCreationError`.
- **`work_in(body)`**는 이전 In-Work Object를 저장하고 body를 In-Work Object로 둔 뒤, 블록 안의
  스케치는 `body.Sketches`에, Part Design feature는 그 body에 만든다. Pad가 In-Work Object를 새
  feature로 옮기므로 **factory 호출마다 직전에** body를 다시 In-Work Object로 둔다. 평면 생성이
  In-Work Object를 되찾을 때도 main body가 아니라 이 body로 돌린다. 블록을 나가면 예외든 아니든
  이전 값으로 되돌린다. 예외 중 복원이 실패하면 원래 예외에 note로 붙이고, 정상 종료 중 실패하면
  `AutomationError`를 낸다. 중첩할 수 있다. `work_in` 밖의 동작은 이전과 같다(In-Work Object를
  건드리지 않는다). main body로 조용히 돌아가는 경로는 없다: 다른 Part의 body는 `ParameterTypeError`,
  없는 이름은 `BodyNotFoundError`다.
- **`get_pad`/`pads` 등 조회**는 `work_in` 안에서 그 body의 `Shapes`를 본다.
- **표시/숨김**은 selection을 캡처하고 body만 선택해 `VisProperties`를 부른 뒤 복원한다
  (`SelectionNotRestoredWarning`). `is_visible`은 위의 read-back이 검증되어 노출했다. 형상이 그대로라도
  보수적으로 model generation을 올린다.
- **`bodies.remove(name, delete_contents=False)`**는 main body와, `delete_contents=True` 없이 내용이
  있는 body를 `BodyRemovalError`로 거부한다. 지운 body 안에 In-Work Object가 있었으면 main body로,
  아니면 원래 값으로 둔다.

**공개 API live 검증.**

```text
통합 테스트 (test_multi_body_live.py, 2 통과)
  body A: pad 20x20x10, body B: pad 30x30x12 + work_in 안에서 만든 offset 평면 위 pocket 10x10x5
  블록 뒤 In-Work Object 복원, 새 wrapper에서 두 body의 feature·스케치 재발견
  부피 A 4000, B 10300, main body의 feature 불변, A 숨김/B 보임 read-back, 다시 보임 후 부피 동일
  내용 있는 body 삭제 거부, work_in 안의 예외 뒤 In-Work Object 복원
A->B 수명 주기 (scripts/acceptance/multi_body_lifecycle.py create / verify-and-remove)
  프로세스 A: AUTO3DX_BODY_A/B 생성, 부피 4000 / 10800, 숨김/보임, 정리 없이 종료
  프로세스 B: 이름으로 재발견, 내용·부피·숨김/보임 확인, 두 body만 삭제, 기준 상태와 정확히 같음
enclosure (scripts/acceptance/multi_body_enclosure.py create / verify / remove, 각각 새 프로세스)
  OuterHousing / LEDTray / ElectronicsFloor / SpeakerMounts / MountingBosses, body마다 pad 하나
  create에서 OuterHousing 숨김 -> verify(새 프로세스)에서 OuterHousing 숨김, 나머지 네 개 보임과
  부피 12000 / 14400 / 9000 / 1500 확인, OuterHousing 다시 보임 -> remove 후 기준 상태와 같음
전체 통합 테스트 (같은 Part): 40 통과, 6 skip, 실행 뒤 기준 상태와 같음
```

**정리 중 발견.** `planes.remove(plane)`은 평면만 지우고 `auto_3dx_Planes` 세트는 남긴다. 테스트가
그 세트를 새로 만들었고 비어 있을 때만 세트를 지우도록 Multi-Body와 Multi-sections Solid 통합 테스트의
정리를 고쳤다. 빈 main body를 측정할 수 없으므로 측정·Mirror 통합 테스트는 main body가 비어 있으면
skip한다.

지원하지 않는 것: boolean 연산(Add/Remove/Intersect/Assemble), body 이름 바꾸기와 순서, body 안의 기하
세트, Product/Assembly, In-Work Object의 공개 setter(`work_in` 밖), 비활성 Part의 topology·삭제·표시.

### 1.10 body 단위 topology·update·측정 (probe 42, 실측 2026-09-18)

모든 실행은 빈 테스트 Part `3D Shape00422558`에서만 했고, 매번 기준 상태로 복원했다.

**topology는 body로 범위를 좁힐 수 있다.** 지금까지 "`Topology.Edge,sel`은 전체를 돌려준다"로
기록돼 있었는데(1.2.2.2), 그때는 아무것도 선택하지 않은 상태였다. body 하나를 **먼저 선택하면**
그 body만 검색된다.

```text
Search('Topology.Edge,all')                    -> 32 (두 body의 모서리가 한 목록에 섞여 나온다)
Selection.Add(MainBody); Search('...Edge,sel') -> 16, owner: MAIN_PAD / MAIN_SKETCH
Selection.Add(ToolBody); Search('...Edge,sel') -> ToolBody 것만
Selection.Add(body);     Search('...Face,sel') -> 그 body의 면만 (재빌드 안 된 body는 0개)
Search('Topology.Edge,in')                     -> 전체 (범위 지정 아님)
ToolBody를 In-Work로 두고 MainBody를 선택 + ,sel -> MainBody 것. 선택을 따르고 In-Work Object는 무시한다
```

**모서리·면의 소유 body를 모델에서 읽을 수 있다.** `Reference.Parent`가 그 참조를 만든 feature이고,
거기서 `Parent`를 따라 올라가면 `Body`가 나온다.

```text
솔리드 모서리      Reference.Parent -> Pad:MAIN_PAD -> Shapes -> Body:PartBody -> Bodies
스케치 wire 모서리  Reference.Parent -> Sketch:TOOL_SKETCH -> Pad:TOOL_PAD -> Shapes -> Body:TOOL_BODY
```

body의 모서리에는 그 body가 소비한 **스케치의 wire 모서리도 섞여 있다.** fillet은 솔리드 모서리만
받으므로 `owner_feature_name`으로 골라야 한다(라이브에서 wire 모서리에 fillet을 걸었더니
`AddNewEdgeFilletWithConstantRadius`가 실패했다).

> 1.0.0: 이제 `Edge.from_sketch`가 소유자 이름이 body의 `Sketches`에 있는지로 이 모서리를 구분하고,
> `EdgeQuery.solid()`가 걸러내며, `part.geometry.edges()`/`find_edge`와 인접 쿼리는 처음부터 제외한다.

이 사실로 `part.topology.edges(body=...)`/`faces(body=...)`와 `Edge`/`Face`의 `owner_body`,
`owner_body_name`, `owner_feature_name`, 그리고 `CrossBodyReferenceError` 가드를 만들었다. 소유
정보는 스냅샷을 찍을 때마다 모델에서 다시 읽으므로 새 프로세스에서도 그대로 동작한다. Python에
저장해 두는 것은 없다.

**비어 있는 답은 거부하지 않는다.** CATIA가 소유 body를 알려주지 않으면(`owner_body is None`)
가드는 통과시킨다. 없는 답을 근거로 막으면 정상 호출이 깨지기 때문이다. 이것이 이 가드의 유일한
구멍이다.

**non-main body는 따로 재빌드해야 한다.**

```text
work_in에서 ToolBody에 pad 생성 직후
  IsUpToDate(Part) False / IsUpToDate(MainBody) True / IsUpToDate(ToolBody) False
  measure(ToolBody) -> GetArea E_FAIL (AutomationError)
Part.UpdateObject(ToolBody)  -> ToolBody만 up to date, MainBody는 그대로 False,
                                In-Work Object도 그대로
measure(ToolBody) -> 4800 mm3 (20x20x12)
Part.Update()                -> 전체. 이 세션에서는 ToolBody도 함께 up to date가 됐다
```

`Part.Update()`가 non-main body를 재빌드하지 못한 사례가 보고됐지만 이 Part에서는 재현되지
않았다. 어느 쪽이든 body 하나만 확실히 재빌드하는 경로가 필요하므로 `body.update()`와
`part.update(body)`(둘 다 `Part.UpdateObject`)를 만들었다. 측정 전에는
`Part.IsUpToDate(body)`를 먼저 보고 `TargetNotUpToDateError`로 거부한다. 측정은 읽기 전용이므로
스스로 재빌드하지 않는다.

**EnumParam에는 `Value`가 없다.**

```text
EnumParam (Coincidence.1\Mode, Parallelism.1\Mode 등 스케치 제약이 만든다)
  .Value          -> AttributeError
  .ValueAsString()-> 'CstAttr_Mode_Constrained'   (property가 아니라 메서드)
  .ValueAsInt / .EnumeratedValues / .ValuationType -> 없음
  public 멤버: Application, Comment, Context, GetItem, Hidden, IsTrueParameter, Name,
               OptionalRelation, Parent, ReadOnly, Rename, Renamed, UserAccessMode,
               ValuateFromString, ValueAsString, ValueEnum
```

제약이 하나라도 있는 Part는 이런 파라미터를 갖게 되므로 `Parameter.value`는 `Value`가 없으면
`ValueAsString()`을 읽는다. 쓰기(`ValuateFromString`)는 검증하지 않았으므로 `set()`은 여전히
거부한다.

**새로 만든 평면은 재빌드 전에는 스케치 support로 못 쓴다.** 이건 알려진 현상이었고, 이번에
**상태를 미리 읽을 수 있다**는 것을 확인했다.

```text
planes.create_offset(...) 직후
  IsUpToDate(Part) False / IsUpToDate(plane) False
  sketches.create(support=plane) -> E_FAIL 0x80020009
part.update() 뒤
  IsUpToDate(plane) True / sketches.create(support=plane) -> 성공
```

그래서 `SketchCollection`이 support 평면의 `IsUpToDate`를 먼저 보고 `SupportNotUpdatedError`로
거부한다. 상태를 읽지 못하면 막지 않고 CATIA에 맡긴다.

**PartUpdateError는 대개 되돌리면 낫는다.**

```text
pad 30mm + fillet 5mm, update 성공, 부피 47785.398
pad.set_height(1.0) -> update 실패 (PartUpdateError), IsUpToDate False, fillet은 트리에 그대로
pad.set_height(30.0) -> update 성공, IsUpToDate True, 부피 47785.398로 복귀, fillet 그대로
```

즉 **정상이던 값을 바꿔서 실패한 경우는 그 값을 되돌리는 것이 먼저**이고, feature 삭제는 새로
만든 feature가 애초에 만들어지지 않았거나 되돌릴 값이 없을 때만 한다. 기존 문서·docstring의
"실패한 feature를 지워야 한다"는 안내를 이에 맞게 고쳤다.

**여전히 남은 한계.** feature 단위 범위 지정은 없다(`Topology.Edge,in,<name>` 등은 probe 35에서
전부 실패). 모서리 index와 BRep 이름은 재빌드마다 바뀌고 프로세스를 넘겨 저장할 수 없다.
`_GenerationRegistry`는 프로세스 안에서만 유효하므로, 새 프로세스는 스냅샷을 새로 찍어야 한다.

### 1.11 기존 모델 편집: feature 치수, 스케치 요소 재발견, work_at, 파라미터 의존성 (probe 43, 실측 2026-09-18)

모든 실행은 빈 테스트 Part `3D Shape00422558`에서만 했고, 매번 기준 상태로 복원했다.

**feature 치수 검증 표.** `dir()`에 보이는 것이 아니라 읽기·쓰기·update·형상 변화·새 wrapper까지
확인한 것만 공개했다.

| feature | 치수 | Automation 멤버 | 읽기 | 쓰기 | update | 형상 변화 | 새 wrapper | 새 프로세스 | 공개 API |
|---|---|---|---|---|---|---|---|---|---|
| Edge Fillet | 반지름 | `Radius` (Length) | O | O 4→8 | O | O 47862.7→47450.6 | O | O | `radius` / `set_radius` / `radius_parameter` |
| Chamfer | 길이1 | `Length1` (Length) | O | O 2→5 | O | O | - | - | `length1` / `set_length1` |
| Chamfer | 각도 | `Angle` (Angle) | O | O 45→30 | O | O | - | - | `angle` / `set_angle` |
| Chamfer | 길이2 | `Length2` (Length) | O | **X** `CATIALength: The method Value failed` | - | - | - | - | 없음 (이 SDK가 만드는 길이/각도 모드에서 쓰기 거부) |
| Hole | 지름 | `Diameter` (Length) | O | O 10→12 | O | O | - | - | `diameter` / `set_diameter` |
| Hole | 깊이 | `BottomLimit.Dimension` (Length) | O | O 5→12 | O | O 47303.9→46512.2 | O | O | `depth` / `set_depth` |
| Shell | 내부 두께 | `InternalThickness` (Length) | O | O 2→4 | O | O | - | - | `internal_thickness` / `set_internal_thickness` |
| Shell | 외부 두께 | `ExternalThickness` (Length) | O | O 0→1.5 | O | O 11712→21955.5 | - | - | `external_thickness` / `set_external_thickness` |
| Thickness | 두께 | `Offset` (Length) | O | O 3→6 | O | O 52800→57600 | O | O | `offset` / `set_offset` |
| Pad / Pocket | 깊이 | `FirstLimit.Dimension` | O | O | O | O | O | O | 이미 있음 (`depth`/`height`) |
| Shaft / Groove | 각도 | `FirstAngle`/`SecondAngle` | O | O | O | O | O | O | 이미 있음 |
| Hole | `Depth` | — | **멤버 없음** | - | - | - | - | - | 없음 (깊이는 `BottomLimit`에 있다) |
| Thickness | `Thickness`/`Value` | — | **멤버 없음** | - | - | - | - | - | 없음 (멤버 이름은 `Offset`) |
| Chamfer | `Mode`/`Propagation` | int | O | 미시도 | - | - | - | - | 없음 (파라미터가 아니라 정수) |
| RectPattern | 간격/개수 | 미조사 | - | - | - | - | - | - | 없음 (패턴은 생성·삭제만 검증돼 있다) |
| MultiSectionSolid | — | 단순 치수 없음 | - | - | - | - | - | - | 없음 |

setter는 `part.update()`를 부르지 않는다. 라이브에서 setter 직후 측정은
`TargetNotUpToDateError`로 거부됐고(Phase 1 가드), update 뒤에야 부피가 바뀌었다. 즉 "setter가
몰래 재빌드하지 않는다"가 관측으로 확인된다. 실패한 update는 이전 값을 되돌리고 다시 update하면
복구된다(1.10과 같은 규칙, fillet 8→4로 부피까지 원복 확인).

**스케치 요소 재발견.**

```text
Sketch.GeometricElements            -> Count/Item(i) 그리고 Item("Line.1")처럼 이름으로도 조회된다
  내용                               -> ['AbsoluteAxis'(Axis2D), 'Line.1', 'Line.2', 'Circle.1']
Item('없는 이름')                     -> com_error (HRESULT 0x80020003)
Circle2D.Radius                     -> 5.0 (읽기 O)
Line2D 멤버                          -> Application, Construction, GeometricType, GetItem,
                                       HorizontalReference, Name, Origin, Parent, ReportName,
                                       VerticalReference  (좌표 접근자 없음)
Circle2D.GetCenter()                -> com_error
edit() 없이 Name 읽기                 -> 동작
edit() 안에서 AddBiEltCst(재발견 요소) -> 'Parallelism.1' 생성, update 성공
```

즉 **이름이 스케치 요소의 지속 identity**이고, 인덱스는 아니다. 이 사실로
`sketch.get_element(name)`/`sketch.elements()`와 `SketchElement.name`/`radius`를 만들었다.
선 좌표는 이 단계에서 `Line2D`가 노출하지 않는다고 보고 넣지 않았다. **Phase 5에서 정정:**
`GetEndPoints(seed)`로 읽히며 `SketchElement.geometry()`로 공개했다(1.14). 같은 두 선에 같은
parallelism을 다시 걸면 CATIA는 중복을 만들지 않고 기존 것을 둔다(프로세스 B에서 개수 1→1).

**feature를 In-Work Object로 두면 그 뒤에 삽입된다.**

```text
tree before        ['AUTO3DX_P43_PAD', 'AUTO3DX_P43_FILLET']
IWO before         AUTO3DX_P43_FILLET (마지막으로 만든 feature)
Part.InWorkObject = PAD    -> IWO inside: AUTO3DX_P43_PAD
그 상태에서 pad 생성        -> 'AUTO3DX_P43_PAD2', IWO는 새 pad로 이동
tree after         ['AUTO3DX_P43_PAD', 'AUTO3DX_P43_PAD2', 'AUTO3DX_P43_FILLET']
update             성공, is_up_to_date True, 부피에 두 pad 모두 반영
```

즉 **선택한 feature "바로 뒤"에 삽입**되고, 그 뒤의 fillet은 여전히 하류에 남는다. 트리 재정렬이
아니다(기존 feature는 아무것도 움직이지 않는다). 이 사실로 `part.work_at(feature)`를 만들었다.
`work_in(body)`는 어느 body에 만들지, `work_at(feature)`는 그 body의 history 어디에 만들지를
고른다. 둘은 하나의 스택을 공유하고 안쪽 블록이 이긴다.

**파라미터 의존성은 Relations에서 읽는다.**

```text
Formula 멤버        Activate, Activated, Comment, Context, Deactivate, GetInParameter, GetItem,
                   GetOutParameter, Hidden, IsConst, Modify, Name, NbInParameters,
                   NbOutParameters, Parent, Rename, Value
NbInParameters     1
GetInParameter(1)  '3D Shape00422558\\AUTO3DX_P43_L'  (정규화된 이름)
GetInParameter(2)  com_error (마지막 다음)
Parameter.OptionalRelation  입력 파라미터 -> None / 구동되는 파라미터 -> 'AUTO3DX_P43_FORMULA'
```

`OptionalRelation`은 그 파라미터를 **구동하는** relation(출력 쪽)만 알려주므로, "이 파라미터를
읽는 formula"는 각 formula의 입력을 훑어야 한다. 문자열 파싱은 하지 않는다.

**참조 중인 파라미터를 지우면 생기는 일(수정 전 동작).**

```text
parameters.remove('AUTO3DX_P43_L')  -> 예외 없이 성공
formula 목록                         -> 그대로 남아 있음
formula body                        -> 'deleted_AUTO3DX_P43_L * 2'
is_up_to_date                       -> False
```

그래서 `parameters.remove`는 먼저 `Relations`를 훑어 그 파라미터를 읽는 formula가 있으면
`ParameterInUseError`로 거부한다. `parameters.dependents(name)`이 무엇이 막고 있는지 알려주고,
`force=True`는 위 결과를 감수하겠다는 뜻이다. 지원 경계는 **formula까지**다: rule, check, law,
program, design table은 검증된 입력 목록이 없어 탐지하지 않는다.

**남은 한계.** Chamfer의 `Length2`는 쓰기 불가, 선 좌표는 읽을 수 없고, RectPattern 치수는
미조사다. 요소 이름은 지속되지만 topology의 모서리·면 index와 BRep 이름은 여전히 재빌드마다
바뀐다(1.10).

### 1.12 원형 패턴, boolean, 제약 삭제, feature 억제 (probe 44, 실측 2026-09-19)

모든 실행은 빈 테스트 Part `3D Shape00422558`에서만 했고, 매번 기준 상태로 복원했다.

**AddNewCircPattern의 실제 시그니처** (타입 라이브러리에서 읽음):

```text
AddNewCircPattern(iShapeToCopy, iNbOfCopiesInRadialDir, iNbOfCopiesInAngularDir,
                  iStepInRadialDir, iStepInAngularDir,
                  iShapeToCopyPositionAlongRadialDir, iShapeToCopyPositionAlongAngularDir,
                  iRotationCenter, iRotationAxis, iIsReversedRotationAxis,
                  iRotationAngle, iIsRadiusAligned)      -- 12개
```

**축 매핑은 회전 중심/축에 넘긴 원점 평면이 정한다.** 지름 120, 두께 10 디스크에 반지름 6
구멍 하나(한 구멍 = 1130.973 mm3)를 뚫고 6개 60도로 패턴했다.

```text
PlaneXY / PlaneXY  -> 5654.867 제거 = 정확히 구멍 5개. 즉 Z축 회전 (검증)
PlaneYZ / PlaneYZ  ->  766.234 제거. Z축이 아니다. 구멍들이 디스크 밖으로 나가 일부만 잘림
PlaneZX / PlaneZX  -> 1130.973 제거. 역시 Z축이 아니다
```

디스크 형상으로는 YZ/ZX가 정확히 어느 축인지 확정할 수 없었다. 그래서 Phase 3의 공개 API는
**Z축만** 받았다. 검증 못 한 매핑을 이름만 그럴듯하게 여는 것보다 없는 편이 안전하다.
**Phase 5에서 정정:** 무게중심으로 YZ -> X, ZX -> Y를 확정했고, 원통면·직선 모서리 축도
검증해 공개했다(1.14).

**패턴 파라미터.**

```text
CircPattern 멤버   ActivatePosition, AngularDirectionRow, AngularRepartition,
                  CircularPatternParameters, DesactivatePosition, GetRotationAxis,
                  GetRotationCenter, ItemToCopy, RadialAlignment, RadialDirectionRow,
                  RadialRepartition, RotationAngle, RotationOrientation,
                  SetInstanceAngularSpacing, SetRotationAxis, SetRotationCenter, ...
AngularRepartition 멤버  AngularSpacing, InstanceSpacing, InstancesCount
RadialRepartition       LinearRepartition 타입 (AngularSpacing 없음, Spacing)
RotationCenter/RotationAxis 속성  없음 (Get/Set 메서드만 있다)

InstancesCount 6 -> 8, update -> 구멍 7개 분량 제거로 일치
AngularSpacing 60 -> 45, update -> 반영됨
MainBody.Shapes에 ('이름', 'CircPattern')으로 남아 새 프로세스에서 이름으로 찾힌다
패턴을 지워도 원본 pocket은 남는다
```

**boolean 네 가지 모두 동작한다.** 디스크(111966.362)에 반지름 15 높이 40 원기둥(28274.334,
겹치는 부피 7068.583)을 tool body로 썼다.

| 연산 | 메서드 | 결과 부피 | 해석 |
|---|---|---|---|
| Remove | `AddNewRemove(tool)` | 104897.779 | 겹친 7068.583 제거 |
| Add | `AddNewAdd(tool)` | 133172.113 | 밖에 있던 21205.751 추가 |
| Intersect | `AddNewIntersect(tool)` | 7068.583 | 겹친 부분만 남음 |
| Assemble | `AddNewAssemble(tool)` | 133172.113 | 이 형상에서는 Add와 같음 |

```text
인자                 tool body 하나뿐 (AddNewRemove(iBodyToRemove))
대상                 In-Work Object인 body. work_in(target)으로 고른다
생성 후 tool body    InBooleanOperation True, 그리고 Part.Bodies에서 사라진다
feature 멤버         Application, Body, GetItem, Name, Parent, SetOperatedObject,
                    SetOperatingVolume   (AffectedBody/ToolBody 같은 건 없다)
result.Body.Name    소비된 tool body 이름 -> 새 프로세스에서도 읽힌다
```

**boolean 삭제는 소비된 body까지 지운다.** feature를 지우면 대상 body의 부피는 원래대로
돌아오지만 tool body는 **돌아오지 않는다**(`Bodies`에도 없고 이름으로도 못 찾는다). 되돌릴
방법이 확인되지 않았으므로 `remove_boolean(name, delete_consumed_body=True)`로 명시하게 했다.

**제약 삭제.** `Constraints.Remove(iIndex)`는 **인덱스**를 받는다(이름이 아니다). 살아 있는
스케치에서 두 경로 모두 성공했다.

```text
스케치 닫힌 채 Remove(1)            -> count 3->2, broken 0, update 성공
OpenEdition + Remove(1) + CloseEdition -> count 2->1, broken 0, update 성공
Constraints.Item("이름")            -> 동작 (조회는 이름으로 된다)
Constraint 객체끼리 COM 동일성 비교   -> 실패. 인덱스는 이름으로 찾아야 한다
```

SDK는 edition 경로를 쓴다. 제약 생성이 이미 그 경로이고, solver를 열어둔 채 두는 것이 스케치를
깨뜨리는 원인이기 때문이다. 이미 `with sketch.edit()` 안이면 열린 세션을 재사용한다(중첩
`OpenEdition`은 미검증).

**feature 억제는 Activity 파라미터로 한다.**

```text
feature.Activity            -> 멤버 없음
feature.GetItem("Activity") -> com_error
Part.Parameters.Item("<Part>\\<Body>\\<Feature>\\Activity") -> BoolParam   <- 이 경로
Parameters 전체를 "\\<Feature>\\Activity"로 훑어도 정확히 하나 나온다 (대비 경로)
feature.Parent 체인          Shapes -> Body -> Bodies -> Part(Parameters 보유)
```

```text
fillet Activity True -> False, update  -> 부피 111931.591 -> 111966.362 (필렛 효과 사라짐)
                                          feature는 트리에 그대로
False -> True, update                  -> 111931.591로 정확히 복귀
Activity를 쓰면 즉시 is_up_to_date False (update 전)
```

**상류 feature를 억제하면 하류가 깨진다.** pad를 억제하고 update하면 `Part.Update()`가
**실패**하고(PartUpdateError) Part는 not-up-to-date가 된다. 하류 fillet은 트리에 남고 Activity도
True 그대로이며, 측정은 Phase 1 가드에 걸린다. pad Activity를 되돌리고 update하면 완전히
복구된다. 즉 1.10의 "먼저 되돌려라" 규칙이 억제에도 그대로 적용된다. 의존성을 미리 판단해
주지는 않는다.

**공개 세션 API.** acceptance 스크립트에서 raw COM을 없애기 위해 `catia.active_window_title`
하나만 열었다(읽기 전용). 창 조작은 하지 않는다.

**남은 한계.** 원형 패턴의 X/Y축과 반경 방향 행, `RotationAngle`/`RotationOrientation`,
`ActivatePosition`으로 개별 인스턴스를 끄는 것, boolean으로 소비된 body를 되살리는 것,
rect 패턴의 치수 편집은 모두 미검증이다.

### 1.13 기하 사실 측정, 방향, 평면 편집, update 진단 (probe 45, 실측 2026-09-20~21)

모든 실행은 빈 테스트 Part `3D Shape00422558`에서만 했고, 매번 기준 상태로 복원했다.

**측정 경로는 `MeasurableService`다.**

```text
Editor.GetService("MeasurableService").GetMeasurable(reference, CATMeasurableType)
  -> win32com.client.CastTo(item, "MeasurablePlane" | "MeasurableCylinder" | ...)
CATMeasurableType  Circle=2 Cone=3 Curve=4 Cylinder=5 Line=6 Plane=7 Sphere=9 Surface=10
                   (probe 31이 넘긴 1은 틀린 값이었다)
MeasureService.GetMeasureItem의 분류 값  -> 모든 요소에 unknown(5/5/7). 쓰지 않는다
측정은 모델을 바꾸지 않는다 (generation 불변, update 상태 불변)
```

**단위가 섞여 있다.**

| getter | 단위 | SDK 변환 |
|---|---|---|
| `GetArea` | **m²** | ×1e6 → `area_mm2` |
| `GetCOfG`, `GetPerimeter`, `GetRadius`, `GetLength`, `GetPoints`, `GetPlane` | mm | 그대로 |
| `GetAngle` (원) | deg | 그대로 |

**Cast는 실패하지 않는다. 분류는 "어느 typed getter가 답하느냐"로 한다.**

```text
면  MeasurablePlane.GetPlane([0.0]*9) 성공 -> 평면 (origin, u, v)
    Cylinder.GetRadius 성공 + Cone.GetAngle 실패 + Sphere.GetCenter 실패 -> 원통
    Sphere.GetRadius는 원통에서도 성공한다 -> 판별에 쓰지 않는다
    그 밖 -> "unknown"
모서리  MeasurableCurve.GetPoints(seed, seed, seed) -> (start, mid, end), 모든 모서리에서 성공
    Circle.GetRadius/GetCenter/GetAngle 성공 -> 원 (angle 360) 또는 호
        필렛 호 r=3 angle 90, 구멍 테두리 r=5 angle 360
    Circle 실패 + |end-start| = length + mid가 정확히 중점 -> 직선
    Line getter는 원에서도 답하지만 값이 쓰레기다 -> 판별에 쓰지 않는다
    그 밖 -> "unknown"
```

**평면 법선(u×v)의 부호는 바깥 방향이 아니다.** 블록의 윗면과 아랫면이 **둘 다 +Z**였다.
옆면은 우연히 바깥이었다. 그래서 SDK는 법선을 축으로만 쓰고(`normal_parallel`은 부호 무관),
"윗면"은 `extreme((0, 0, 1))`처럼 중심 위치로 고른다.

**owner는 provenance가 아니다.** 필렛 뒤에는 필렛이 건드리지 않은 모서리까지 솔리드 모서리 전부의
`Reference.Parent`가 FILLET이었다. 마지막으로 결과를 만든 feature다.

**Parent 체인은 세션에 따라 body에 닿지 않는다.** 2026-09-21 3DEXPERIENCE 재시작 뒤, pad가
소비한 스케치의 wire edge에서 `Parent`를 따라가니 `Sketch -> AnyObject:CATIABase1481 ->
AnyObject:CATIABase1482 -> ...`로 Body가 나오지 않았다(probe 42에서는 `Sketch -> Pad -> Shapes ->
Body`). 솔리드 모서리는 여전히 Body에 닿았다. 그래서 체인이 실패하면 Part의 모든 body의
`Shapes`/`Sketches`에서 그 feature 이름을 찾아, **정확히 한 body**에만 있을 때 그 body로 본다
(`_topology_search.BodyIndex`). 둘 이상이면 모른다(None)로 둔다.

**Pad/Pocket 방향은 `DirectionOrientation`이다.**

```text
0 = 스케치 법선 방향(along), 1 = 반대(against). Pad와 Pocket 모두 같은 의미
CATIA 기본값    Pad 0, Pocket 1
블록 아래 XY 스케치의 기본 pocket   -> 제거 0 mm3, update 성공  (zero-effect pocket)
같은 pocket을 0으로                 -> 제거 502.655 mm3 = 기대값 정확히 일치
Pad를 1로                           -> 무게중심 z가 -방향으로 이동
```

**평면 편집.**

```text
HybridShapePlaneOffset.Offset.Value 40 -> 55, update -> 스케치와 pad가 따라 이동, 새 wrapper가 55를 읽음
HybridShapePlaneAngle.Angle.Value 30 -> 45, update   -> 스케치 frame 회전
편집 전후 모두 sketch frame == plane frame
Sketch에는 support 멤버가 없다 -> 의존 스케치는 frame 비교로 찾는다
사용 중인 평면 삭제 -> 성공하지만 스케치와 pad가 고아가 되고 다음 update가 실패한다
```

**update 진단.**

```text
Part.IsUpToDate(feature), Part.IsInactive(feature)  -> 둘 다 동작
base pad 억제: pad IsUpToDate True, IsInactive True / 하류 fillet IsUpToDate False
fillet 반지름 500: fillet만 표시된다
acceptance, boss 높이 1: RIM_FILLET과 SLOT이 표시되고 boss는 표시되지 않았다
-> "up to date 아님"은 증상이지 원인이 아니다
```

**그 밖.**

```text
Sketch.rectangle()           -> 선 4개, 제약 0개 (구속 헬퍼는 다음 단계)
원형 패턴 씨앗 pocket 삭제   -> 그 스케치는 함께 지워지지 않는다. 스케치를 따로 지워야 한다
```

**성능** (18면 + 41모서리 = 59요소, 원형 패턴 12개가 있는 판):

```text
faces + edges 스냅샷      1.024 s
59요소 전부 측정          0.588 s (요소당 약 10 ms)
측정된 스냅샷에서 쿼리 2개  1.1 ms
새 edge 스냅샷 + 측정 쿼리  0.873 s
```

### 1.14 Phase 5: 스케치 읽기, 면 위 스케치, Hole 위치·한계, 패턴 축 (probe 46 계열, 실측 2026-09-27)

모든 실행은 빈 테스트 Part `3D Shape00422558`에서만 했고, 매번 빈 기준 상태로 복원해 다시 확인했다.

**단일 probe가 CATIA를 멈추게 했다.** 처음의 probe 46은 한 번에 스케치 요소를 만들고, 열린 편집
안에서 `GetEndPoints`/`GetOrigin`/`GetDirection`/`CenterPoint.GetCoordinates`/`GetParamExtents`
등을 읽고, 사각형에 제약 여러 개를 걸었다. 그 단계에서 3DEXPERIENCE가 CPU 한 코어를 쓴 채 응답
없음이 됐고 출력이 버퍼링돼 호출을 특정하지 못했다(사용자가 재시작, 대상 Part에는 남은 것이
없었다). 이후로는 질문 하나당 micro-probe 하나(`scripts/probes/46*.py`, 공통 틀 `_micro.py`):
대상·빈 기준 확인, 모든 Automation 호출 앞뒤에 flush된 BEFORE/AFTER 마커, `python -u`, 정리 뒤
기준 재확인. 29개 모두 멈추지 않았다. **타입 라이브러리에 있다는 것은 런타임에 안전하다는 뜻이
아니다.**

**스케치 읽기 (편집을 닫은 뒤)**

```text
Line2D.GetEndPoints([0]*4)        -> (10, 5, 40.00000000000001, 25.000000000000007)   46a
Circle2D.GetCenter([0]*2)         -> (20, 15)   probe 43은 seed 없이 불러 실패했다     46b
Circle2D.Radius                   -> 4.0
호 CreateCircle(-20,-10,6,0,pi/2) -> GetEndPoints (-14,-10,-20,-4): 매개변수는 radian   46c
닫힌 원 GetEndPoints              -> 시작 == 끝 (2e-15 차이). 호는 다르다               46ab
Point2D.GetCoordinates([0]*2)     -> (-5, 7.5)                                          46g
Construction 읽기                 -> False / True                                       46f
Constraint.Mode                   -> 0 (driving), Status 0, Type 5, Dimension.Value 30  46d
GetConstraintElement(1)           -> Reference, DisplayName 'Line.1'                    46e
GetConstraintElement(1)/(2)       -> 수직 제약의 'Line.1', 'Line.2'                      46ac
GeometricElements.Item(name)      -> 새 attach에서도 같은 값. 첫 요소는 AbsoluteAxis(Axis2D) 46h
열린 편집 안에서의 읽기           -> 일부러 반복하지 않았다. 멈춤의 용의자 (UNKNOWN)
```

SDK는 편집이 열린 동안의 geometry 읽기를 COM 전에 `ValidationError`로 거부한다.

**평면 면 위 스케치**

```text
Sketches.Add(<윗면 Reference>)      -> Sketch, frame (0,0,20 | X | Y), update 성공         46i
아랫면                             -> (0,0,0 | X | -Y), 법선 -Z = 재료 바깥                46j
+X 옆면                            -> (30,-20,0 | Y | Z), 법선 +X = 재료 바깥. 원점은 면 중심이 아니다
포켓 바닥(오목한 면)               -> (0,0,16 | X | Y), 법선 +Z = 재료 바깥               46aa
윗면 스케치 로컬 (10,5) 원 + pocket 기본 방향(DirectionOrientation 1)
                                   -> 정확히 113.097 mm3 제거, 보어 중심 (10,5,18)          46k
pad 높이 20 -> 30, update          -> 스케치 원점 z 30, pocket이 면을 따라감               46l
원통면 위 스케치                   -> 시도하지 않음. SDK가 평면이 아닌 면을 COM 전에 거부
```

그래서 SDK가 면 위에 만든 스케치에 한해 "into_material" = 법선 반대, "out_of_material" = 법선 방향으로
답한다. 다시 찾은 스케치는 support를 읽을 멤버가 없어 이 판단을 하지 않는다.

**Hole**

```text
AddNewHoleFromPoint(10,5,20, 윗면, 8) -> GetOrigin (10,5,20) update 전후 동일, 보어 중심 (10,5,16)  46m
기본값                              -> Diameter 12, LimitMode 0, BottomType 1(V), BottomAngle 120
BottomLimit.LimitMode = 2           -> 20 mm 관통 정확히. CATIA가 깊이 치수를 8 -> 20으로 다시 씀   46n
  다시 0                            -> 깊이는 20 그대로. blind로 돌아갈 때 깊이를 다시 줘야 한다
BottomType = 0                      -> 평평한 바닥, 정확한 원통 부피                              46o
새 Hole (아무것도 안 씀)            -> 직전 Hole의 BottomType 0을 물려받음                          46q
  BottomAngle (평평할 때)           -> E_FAIL
BottomType = 1                      -> V, 120, 46m과 같은 부피                                    46r
Diameter/BottomType/LimitMode를 첫 update 전에 모두 씀 -> 정확한 관통 부피                          46s
+X 옆면 Hole GetDirection           -> (-1,0,0): 재료 안쪽                                        46p
Reverse/SetOrigin/SetDirection/나사/카운터보어 -> 호출하지 않음 (TYPELIB_ONLY)
```

> 1.0.0: 그 뒤 47 시리즈가 `SetOrigin`(47m), `Reverse`(47g, 제거량 0), 카운터보어·카운터싱크(47h),
> up-to-next(47f), 원 경계 면 위 편심 Hole의 중심 스냅(47d)을 실측했다. `SetDirection`과 나사는 여전히
> 호출하지 않는다. `docs/api-design.md` 21.3절과 부록 A.

**Hole 설정은 세션 상태로 이어진다.** Phase 5 live 스테이지가 관통 Hole을 만든 뒤, 기존 Phase 2 테스트의
`create_hole(name, face, 5.0)`이 관통 Hole(깊이 30)이 되어 실패했다. LimitMode도 BottomType처럼 이어진다.
그래서 `create_hole`은 이제 limit을 항상 명시적으로 쓴다(깊이가 있으면 blind). 지름과 바닥은 넘긴 경우에만
쓴다. 상위 API는 모두 쓴다. `scripts/probes/46af_restore_hole_session_defaults.py`가 세션 기본값을
(12, V, blind)로 되돌리고 새 Hole로 확인한다.

**원형 패턴**

```text
큐브(중심 (25,0,5)) 4 x 90도
  PlaneYZ를 중심·축으로  -> COG (25,0,0): X축                                           46t
  PlaneZX                -> COG (0,0,0):  Y축
  PlaneXY                -> COG (0,0,5):  Z축
원통면 Reference (허브 r5, (50,40)) -> 부피 4785.398, COG (50,40,5): 허브 축              46u
직선 모서리 Reference ((30,5) 수직) -> 부피 4000, COG (30,5,5): 모서리 축                 46v
CircularPatternParameters = 1 (complete crown) -> 기록·읽기는 되지만 형상은 10도 간격 그대로 46w
  기본값 읽기                     -> E_FAIL
iIsReversedRotationAxis False/True (Z축) -> 복사본이 -Y / +Y: +Z에서 볼 때 시계 / 반시계   46x
Hole을 씨앗으로 6개, 360도 (live stage 10) -> 정확히 6개 분량, instances=4로 바꾸면 4개 분량
```

**인접 관계는 검증된 경로가 없다.**

```text
면 하나 선택 + Search("Topology.Edge,sel")           -> 0개                                 46y
MeasurableBetween.DistanceMinToPoint(x,y,z [, seeds]) -> "Invalid number of parameters"      46z, 46z2
```

대신 `EdgeQuery.on_plane_of(face)`는 측정된 시작·중간·끝점이 그 면의 평면 위에 있는 모서리를 남긴다.
평면 사실이지 인접이 아니다.

> 1.0.0: 46z가 실패한 것은 측정 유형을 평면(7)으로 요청했기 때문이었다. `GetMeasurable(face, 1)`은
> `MeasurableBetween`이고 `DistanceMinToPoint(x, y, z)`는 **경계가 있는 면**까지의 거리를 준다(47l).
> 이것으로 측정 기반 인접(`EdgeQuery.adjacent_to`, `FaceQuery.adjacent_to`,
> `part.topology.edges_of`/`faces_of`)을 구현했다. `docs/api-design.md` 21.2절.

**사각형 제약**

```text
H(아래), H(위), V(오른쪽), V(왼쪽)          -> 4개 모두 Parallelism(8), 상태 0, update 성공  46ad
+ 길이(아래)=12, 길이(왼쪽)=8               -> 6개, 상태 0, update 성공                   46ae
```

모서리 일치 구속(점 제약)은 근거가 없어 "완전 구속" 옵션은 두지 않았다.

> 1.0.0: 47i가 꼭짓점 `Point2D`를 변들이 공유하게 하고(`StartPoint`/`EndPoint`), H/V, 가로, 세로,
> `AbsoluteAxis` 기준 거리 앵커 두 개를 거는 방식을 실측했다. 이것이 `constraints="fully"`다.
> CATIA 솔버의 완전 구속 상태 자체는 읽지 않는다. `docs/api-design.md` 21.4절.

**기타.** 허브 면을 패턴 축으로 쓴 pad를 지웠더니 그 스케치가 **연쇄 삭제되지 않았다**(46u 정리 중
발견). probe 정리는 이제 접두어로 남은 것을 쓸어낸다(`_micro.sweep`). `inspect.facts("volume",
"up_to_date", ...)`는 live에서 0.038 s였다(`summary()`는 1-3.5 s).

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

> **이 절은 `docs/api-design.md`가 대체한다.** 아래 내용은 이력으로 남긴다. 새 코드와 리뷰는 api-design.md를 기준으로 한다.

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

> **이 절은 `docs/api-design.md`가 대체한다.** 아래 내용은 이력으로 남긴다. 새 코드와 리뷰는 api-design.md를 기준으로 한다.

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

> **`docs/api-design.md`가 우선한다.** 아래 모듈별 signature는 각 기능을 만들 당시 확정한 계약의
> 기록이다. 그 뒤 API 설계 계약에 따라 바뀐 것이 있다. 예를 들어 topology는 `part.topology`로
> 옮겼고, 예외는 범주로 묶였으며, 루트 export는 줄었고, 측정은 main body를 기본으로 잰다. 두 문서가
> 다르면 api-design.md를 따르고, 이 절은 그 결정의 이력으로 읽는다.

아래 signature는 해당 기능을 만들 당시 **그대로** 구현하기로 한 것이다. 임의로 이름이나 인자를
바꾸지 않는다는 원칙은 유지하되, 바꿔야 한다면 api-design.md를 먼저 고친다.

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
    def __init__(self, com_object: Any, selection: Any = None, editor: Any = None) -> None: ...

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

    @property
    def measurement(self) -> "SolidMeasurement": ...  # Editor 없으면 NoActiveEditorError

    def is_up_to_date(self, target: Any = None) -> bool: ...

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
    def arc(self, center_x: float, center_y: float, radius: float,
            start_param: float, end_param: float) -> Any: ...
    def spline(self, points: "list[tuple[float, float]]") -> Any: ...
    def set_construction(self, element: Any, construction: bool = True) -> None: ...
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
CONSTRAINT_CONCENTRICITY: int = 3
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
def concentric(self, first: Any, second: Any) -> Constraint: ...
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

### 6.17 Rectangular Pattern

probe 30에서 방향 평면과 부호의 대응을 확인했고, public implementation과 unit 테스트를
추가했다. 공개 adapter의 생성 + `Part.Update()` + 반환 객체 기반 cleanup live integration도
통과했다.

```python
RECTANGULAR_PATTERN_KIND: str = "RectPattern"
PATTERN_DIRECTION_X: str = "X"
PATTERN_DIRECTION_Y: str = "Y"
PATTERN_DIRECTION_Z: str = "Z"
PATTERN_DIRECTION_NEGATIVE_X: str = "-X"
PATTERN_DIRECTION_NEGATIVE_Y: str = "-Y"
PATTERN_DIRECTION_NEGATIVE_Z: str = "-Z"

class RectangularPattern:
    @property
    def com_object(self) -> Any: ...

class PartDesign:
    def create_rectangular_pattern(
        self,
        pad: Pad,
        number_in_direction_1: int,
        number_in_direction_2: int,
        spacing_in_direction_1: float,
        spacing_in_direction_2: float,
        direction_1: str,
        direction_2: str,
    ) -> RectangularPattern: ...

    def remove_rectangular_pattern(
        self,
        pattern: RectangularPattern,
    ) -> None: ...
```

Direction strings are signed global axes, not raw planes. Their signs are the complete public
direction choice: callers never manage CATIA reverse flags. The implementation translates each
signed axis to the verified per-slot origin-plane Reference and CATIA reverse-flag mapping from
1.2.5. The two directions must name different unsigned axes, and each spacing must be strictly
positive and finite; invalid inputs are refused before any reference or COM call. The source must
be an auto_3dx `Pad`, because no other source family has been verified. These methods never update
or save the Part. Name-based lookup and ensure remain unverified, but the exact wrapper returned by
creation can be removed through the owning editor's Selection so an update failure is recoverable.

### 6.18 Measurement

```python
@dataclasses.dataclass(frozen=True)
class MassProperties:
    volume_mm3: float
    area_mm2: float
    mass_kg: float
    cog_mm: tuple[float, float, float]

class SolidMeasurement:
    def __init__(self, editor_com_object: Any) -> None: ...
    def measure(self, item: Any) -> MassProperties: ...
```

`Part.measurement` obtains this reader from the Part's own `Editor`, not from `Part`, and caches it
on first access. A `Part` constructed without an editor raises `NoActiveEditorError` rather than
guessing. Measurements never update, save, or propagate. Values returned by Inertia services are
SI and are converted at the boundary: lengths to mm, area to mm2, volume to mm3, and mass remains
kg. There is deliberately no bounding box: `InertiaBoxService` returned a real box in one session
and all zeros in another on the same unchanged model, so it is not shipped (1.4). Probe 30 is the
original live verification; the measurement integration test now passes against a live session.

### 6.19 Part rebuild status

`Part.IsUpToDate(iObject)`는 B428_Cloud에서 `VT_BOOL`을 반환한다. public API는
다음과 같다.

```python
class Part:
    def is_up_to_date(self, target: Any = None) -> bool: ...
```

`target=None`이면 raw Part 자신을 넘긴다. auto_3dx wrapper는 `com_object`를
풀어서 넘기고 raw CATIA dispatch도 허용한다. 반환값이 bool이 아니거나 COM 호출이
실패하면 `Auto3dxError`다. 이 메서드는 update/save/propagate를 호출하지 않는다.

probe 32와 live integration에서 Pad 높이를 변경한 직후 Part/MainBody/Pad는
`False`, 영향받지 않은 Sketch는 `True`였고, `Part.Update()` 뒤 모두 `True`가
됐다. 반면 독립 사용자 Parameter의 생성·값 변경만으로는 Part/MainBody가 계속
`True`였다. 따라서 이 값은 **feature rebuild 상태**이며, 일반적인 dirty flag나
unsaved-change 감지로 해석하면 안 된다.

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

Stiffener는 미검증이므로 구현하지 않는다. Slot과 Rectangular Pattern은 각각 6.16과 6.17의
계약으로 구현돼 있다. Pattern은 생성과 반환 객체 기반 삭제만 노출하고 named lookup,
ensure, mutation은 미검증으로 남긴다.

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

> **이 절은 `docs/api-design.md`가 대체한다.** 아래 내용은 이력으로 남긴다. 새 코드와 리뷰는 api-design.md를 기준으로 한다.

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
dependencies      : pywin32 (sys_platform == "win32")
extras            : test = pytest>=8
```

`com3dx`는 의존성이 아니다. 3DEXPERIENCE 설치본에 들어 있고 `transport.windows_com`이
실행 시점에 찾는다. 설치는 어떤 Python 환경이든 같다.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
```

Conda에서는 환경을 활성화한 뒤 마지막 명령만 실행한다.

---

## 9. 불확실할 때

이 문서의 "검증된 사실"에 없는 COM 동작이 필요해지면:

1. 추측해서 구현하지 않는다.
2. `DSYAutomation.chm` / type library에서 확인한다.
3. 그래도 불확실하면 **작업을 멈추고 보고한다.** 미검증 경로를 조용히 넣지 않는다.
