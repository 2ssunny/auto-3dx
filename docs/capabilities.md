# auto-3dx 기능 현황

이 문서는 **실제로 동작이 확인된 것만** 적는다. 검증 근거는 `scripts/probes/`의 probe와
`tests/integration/`의 통합 테스트다. 라이브 통합 테스트는 실행 중인 3DEXPERIENCE 세션이
없으면 skip되므로, 과거 probe의 성공과 현재 테스트 실행 결과를 구분해서 기록한다.

- 대상 설치본: B428_Cloud
- 실행 환경: `auto-3dx` conda env, Python 3.11.16 (64-bit), pywin32 312
- 현재 정적 검증: **414 unit 통과**
- 현재 라이브 검증: 측정·곡선 스케치·직사각 패턴을 포함한
  **27 integration 통과**

---

## 1. 한 줄 요약

**실행 중인 3DEXPERIENCE 세션에 붙어서, 이미 열려 있는 Part의 파라미터와 형상을 만들고
수정한다.** Part 자체를 만드는 것과 저장하는 것은 하지 않는다.

---

## 2. 지금 가능한 워크플로

```text
[사람]  3DEXPERIENCE UI에서 Part 생성          <- 자동화 불가 (아래 5.1)
   |
[auto-3dx]  attach -> 파라미터 생성/수정
                   -> 스케치 생성 -> 직선·곡선 프로파일 그리기
                   -> 패드 / 포켓 / 회전 / Rib·Slot / 사각 패턴 생성
                   -> formula로 치수 연동
                   -> 결과 측정
                   -> update
   |
[사람]  결과 확인 후 직접 저장                 <- 자동화 안 함 (아래 6)
```

전체 예제는 `examples/build_part.py`에 있다.

```python
from auto_3dx import Catia

catia = Catia.attach()
part = catia.active_part()

part.parameters.ensure_length("WIDTH", 60)
part.parameters.ensure_length("THICKNESS", 12)

sketch = part.sketches.ensure("BASE", support="XY")
with sketch.edit() as editor:
    editor.rectangle(60, 40)
part.update()

part.part_design.ensure_pad("BASE_PAD", sketch, 12)
part.update()
```

---

## 3. 기능별 상태

### 3.1 연결

| 기능 | 상태 | 비고 |
|---|---|---|
| 실행 중인 세션 attach | 동작 | `com3dx.py` 경로를 레지스트리에서 자동 탐색 |
| 설치 경로 수동 지정 | 동작 | 인자 또는 `AUTO_3DX_COM3DX_PATH` 환경변수 |
| Active Editor / Active Part 조회 | 동작 | |
| Assembly context 거부 | 동작 | 실제 타입(`VPMRootOccurrence`)을 메시지에 포함 |
| 새 세션 실행 | **불가** | attach 전용. 3DEXPERIENCE가 이미 떠 있어야 한다 |
| **editor 목록 조회** | 동작 | `editors()` — ActiveObject를 못 읽는 editor도 목록에 남는다 |
| **열린 Part 전부 조회** | 동작 | `parts()` — 각자 자기 editor의 Selection이 연결됨 |
| **이름으로 Part 선택** | 동작 | `part_named(name)` — 탭 상태와 무관. `ActiveEditor`가 UI를 안 따라오는 문제 해결 |

### 3.2 파라미터

| 기능 | 상태 | 비고 |
|---|---|---|
| 목록 조회 (전체) | 동작 | feature 내부 파라미터 포함 |
| 목록 조회 (사람이 만든 것만) | 동작 | `user_parameters()` / `user_names()` |
| 이름으로 조회 | 동작 | 짧은 이름·정규화 이름 둘 다 가능 |
| 값 읽기 | 동작 | |
| 값 수정 | 동작 | Length, mm |
| 생성 | 동작 | 중복 이름·빈 이름·`\` 포함 이름은 거부 |
| ensure (없으면 생성, 있으면 수정) | 동작 | 다른 타입이면 거부 |
| 삭제 | 동작 | `Parameters.Remove` |
| **Real / Integer / String / Boolean** | 동작 | `create_real` 등. 값 쓰기 가능 |
| **임의 magnitude의 Dimension** | 동작 | `create_dimension(name, "Mass", 2)`. 잘못된 magnitude는 COM 호출 전 거부 |
| **magnitude 조회** | 동작 | `parameter.magnitude` — Mass와 Volume 구분 |
| **단위 카탈로그** | 동작 | `parameters.units` — 339 magnitude, 1887 unit |
| **단위 변환** | **하지 않음** | `Value`는 항상 파라미터 자신의 단위. 단위 인자는 확인용 |

### 3.3 스케치

| 기능 | 상태 | 비고 |
|---|---|---|
| 생성 (XY / YZ / ZX 평면) | 동작 | 이름 지정 가능 |
| ensure | 동작 | 축 데이터로 평면까지 비교. 다르면 거부 |
| 이름 변경 | 동작 | |
| 어느 평면인지 조회 | 동작 | `GetAbsoluteAxisData` 비교. 인식 못 하면 `None` |
| 요소 이름 목록 | 동작 | |
| 편집 세션 | 동작 | `with sketch.edit()` — 예외가 나도 반드시 닫힌다 |
| 점 / 선 / 원 | 동작 | |
| 사각형 | 동작 | 닫힌 프로파일 4선분 |
| 호(arc) | 동작 | 열린 `Circle2D` 세그먼트. 시작/끝 parameter의 단위는 미확정 |
| 스플라인(spline) | 동작 | `ControlPoint2D` 배열로 생성. 최소 점 개수는 미확정 |
| Construction 지정 | 동작 | `set_construction()`으로 2D 요소의 `Construction` 설정 |
| 삭제 | 동작 | `Editor.Selection` 경유 |
| **제약(Constraint) 지정** | 동작 | `edit()` 안에서만. 10종 검증 (아래) |
| **치수 제약 값 읽기/쓰기** | 동작 | Length / Radius / Distance. formula로 구동 가능 |
| **제약 상태 조회** | 동작 | `constraints.broken_count` / `unupdated_count` |
| **동심 제약** | 동작 | `edit()` 안에서 서로 다른 두 `Circle2D`에 지정 |
| **제약 삭제** | **불가** | `Constraints.Remove` 미검증 |
| **사용자 정의 평면 위 스케치** | **부분 동작** | offset plane에 스케치는 가능하지만 그 스케치로 Pad 생성은 미검증/실패 |

### 3.4 Part Design

| 기능 | 상태 | 비고 |
|---|---|---|
| 패드 생성 / ensure / 삭제 | 동작 | 스케치 + 높이 |
| 패드 높이 읽기/쓰기 | 동작 | `FirstLimit.Dimension.Value` |
| **포켓 생성 / ensure / 삭제** | 동작 | 스케치 + 깊이. 패드와 구조 동일 |
| 포켓 깊이 읽기/쓰기 | 동작 | |
| **Shaft(회전) 생성 / ensure / 삭제** | 동작 | 스케치에 `set_center_line()` 축 지정 필요 |
| **Groove(회전 컷) 생성 / ensure / 삭제** | 동작 | Shaft와 동일 |
| 회전 각도 읽기/쓰기 | 동작 | `first_angle` / `second_angle`, 기본 360/0도 |
| **Mirror 생성 / ensure / 삭제** | 동작 | 원점 평면을 받는다. BRep 참조 불필요 |
| **Rib / Slot 생성 / ensure / 삭제** | 동작 | 프로파일 + 경로 스케치 2개. Slot은 절삭 |
| **사각 패턴 생성 / 실패 후 삭제** | 동작 | `create_rectangular_pattern()` / `remove_rectangular_pattern(pattern)`. signed axis만 받고 같은 축 조합은 COM 호출 전 거부. 방향 매핑은 probe 26·30, 공개 adapter는 live integration으로 검증 |
| 목록 / 이름 조회 | 동작 | `pads`, `pockets`, `shafts`, `grooves`, `mirrors`, `ribs`, `slots` 분리 |
| formula 대상 파라미터 얻기 | 동작 | `depth_parameter()` / `first_angle_parameter()` |
| **그 외 전부** | **불가** | 아래 참고 |

삭제 시 주의 (실측으로 확인된 비대칭):

```text
패드 삭제   -> 그 스케치까지 연쇄 삭제됨
포켓 삭제   -> 스케치는 남는다. 따로 지워야 한다
```

`ShapeFactory`는 `AddNew*` 메서드를 **90개** 노출한다. 그중 구현된 것은 `AddNewPad`,
`AddNewPocket`, `AddNewShaft`, `AddNewGroove`, `AddNewMirror`, `AddNewRib`, `AddNewSlot`,
`AddNewRectPattern` **8개**다.

나머지가 막힌 이유는 두 가지다.

```text
면/모서리 참조가 필요       Chamfer, EdgeFillet, Shell, Thickness, Draft, Hole
                            -> feature를 통째로 넘기는 것은 거부된다 (실측).
                               유효한 BRep 이름이 있어야 하는데 모델이 바뀌면 깨진다.
생성은 되는데 update 실패    Stiffener, CircPattern
                            -> 객체는 트리에 생기지만 모델이 재계산에 실패한다.
                               "생성 성공"을 검증으로 쳐주지 않는 이유다.
```

미구현 예:

```text
AddNewHole        AddNewChamfer     AddNewEdgeFillet* AddNewDraft
AddNewShell       AddNewThickness   AddNewStiffener
AddNewCircPattern AddNewUserPattern AddNewLoft        AddNewSplit
AddNewTrim        AddNewSolidCombine ... 외 70여 개
```

### 3.4.1 스케치 제약

**제약은 `sketch.edit()` 안에서만 걸린다.** 편집 세션이 닫힌 뒤에는 전부 실패한다. 그래서
생성 메서드는 `SketchEditor`에만 있다 — 위치가 곧 계약이다.

인자는 `line()` / `circle()`이 돌려준 **raw COM 객체를 그대로** 넘긴다. Part Design과 달리
`Reference`로 감싸면 거부된다.

```python
with sketch.edit() as editor:
    bottom = editor.line(0, 0, 40, 0)
    right  = editor.line(40, 0, 40, 25)
    editor.horizontal(bottom)
    editor.perpendicular(bottom, right)
    width = editor.length(bottom, 40)      # 치수 제약
part.update()
```

검증된 10종: `horizontal`, `vertical`, `perpendicular`, `parallel`, `coincident`,
`concentric`, `tangent`, `length`, `radius`, `distance`. 뒤의 셋이 치수 제약이다.

**요청한 타입과 결과 타입이 다를 수 있다.** `horizontal`은 `Parallelism`(Type 8)이 된다.
따라서 요청 코드로 제약을 되찾으면 안 된다.

미구현: 제약 삭제(`Constraints.Remove` 미검증). `concentric`은 서로 다른 원 두 개로 생성과
`Part.Update()`까지 확인했다.

### 3.5 Formula

| 기능 | 상태 | 비고 |
|---|---|---|
| 목록 / 이름 조회 | 동작 | |
| 이름으로 조회 | 동작 | 같은 이름이 둘 이상이면 거부 |
| 생성 | 동작 | 대상 파라미터 + 수식 본문 |
| ensure | 동작 | 본문이 다르면 `Modify`로 갱신 |
| 본문 / 주석 / 활성 상태 읽기 | 동작 | |
| 본문 수정, 이름 변경, 활성/비활성 | 동작 | |
| 삭제 | 동작 | |
| 수식에 쓸 이름 얻기 | 동작 | `relation_name(parameter)` |
| **Law / DesignTable / Check / Program** | **불가** | `Relations`에 있지만 미검증 |

**수식 본문에는 `Parameter.name`을 쓰면 안 된다.** 반드시 `relation_name()`으로 얻는다.

```python
driver = part.parameters.get("THICKNESS")
pad = part.part_design.get_pad("BASE_PAD")

body = f"{part.formulas.relation_name(driver)} * 2"
part.formulas.create("PAD_DRIVER", pad.depth_parameter(), body)
part.update()          # 이제 패드 높이가 THICKNESS를 따라간다
```

실측 확인: `driver 12 -> 패드 24mm`, `driver 20 -> 패드 40mm`.

**formula를 지워도 마지막 계산값은 되돌아가지 않는다.** 대상 파라미터에 그대로 남으므로
원래 값이 필요하면 직접 써 줘야 한다.

### 3.6 Part

| 기능 | 상태 |
|---|---|
| 이름 조회 | 동작 |
| `Update()` | 동작 |
| **`Save()`** | **하지 않음** (아래 6) |
| **feature rebuild 상태** | 동작 | `part.is_up_to_date(target=None)`. feature 변경 전후 false→true 검증. unsaved-change 감지는 아님 |
| **솔리드 측정** | 동작 | `part.measurement`로 부피·면적·질량·무게중심·관성 상자 조회 |

### 3.7 손대지 않은 영역

`Part`가 노출하지만 라이브러리가 쓰지 않는 것:

```text
HybridShapeFactory     GSD surface geometry
Bodies / HybridBodies  MainBody 외 body
Part.Constraints       어셈블리 구속 (스케치 구속은 3.4.1에서 지원)
AxisSystems            축 시스템
OrderedGeometricalSets / UserSurfaces / AnnotationSets
```

---

## 4. 공개 API

```python
from auto_3dx import Catia
```

### Catia

```python
Catia.attach(com3dx_path=None) -> Catia
.name                          # "3DEXPERIENCE"
.active_editor()               # raw Editor COM 객체
.active_part()   -> Part       # ActiveEditor를 따른다
.editors()       -> list[EditorInfo]   # name, object_kind, object_name, is_part
.parts()         -> list[Part]         # 열린 Part 전부
.part_named(name) -> Part              # 탭 상태와 무관하게 선택
```

### Part

```python
.name            # "3D Shape00422534"
.parameters      -> ParameterCollection
.sketches        -> SketchCollection
.part_design     -> PartDesign
.formulas        -> FormulaCollection
.update()        # 실패 시 PartUpdateError
.measurement     -> SolidMeasurement  # editor 기반 read-only 측정
```

### SolidMeasurement / 측정 결과

```python
part.measurement.measure(part.com_object.MainBody) -> MassProperties

MassProperties(
    volume_mm3, area_mm2, mass_kg, cog_mm=(x, y, z)
)
```

측정 서비스는 `Part`가 아니라 해당 `Editor.GetService()`에서 얻는다. 따라서 raw `Part`를
직접 감싼 경우에는 editor를 추측하지 않고 `NoActiveEditorError`를 낸다. CATIA 서비스가
반환하는 길이·면적·부피는 SI 단위(m, m², m³)이므로 public 결과에서 각각 mm, mm², mm³로
변환하고 질량은 kg로 유지한다.

**bounding box는 제공하지 않는다.** `InertiaBoxService`는 존재하고 한 세션에서는 실제
60x40x12 mm 상자를 돌려줬지만, 바뀌지 않은 같은 모델에서 다른 세션에서는 전부 0을
반환했다(부피·무게중심은 그대로 정확했다). 호출 형태를 전부 바꿔봐도 0이었다. 실패하지
않고 0을 돌려주는 측정은 없는 것보다 위험하므로 공개 API에서 뺐다. 애초에 축 정렬이 아닌
주관성축 정렬 상자여서 "X 방향으로 얼마나 큰가"에 답할 수 없었다.

측정은 read-only다. `measure()`는 `Part.Update()`, `Save()`, `PLMPropagate()`를
호출하지 않는다.

### ParameterCollection

```python
.count
.list()          -> list[Parameter]     # 전체 (feature 내부 포함)
.names()         -> list[str]
.user_parameters() -> list[Parameter]   # 사람이 만든 것만
.user_names()    -> list[str]           # short_name
.get(name)       -> Parameter
.set(name, value, unit="mm")
.create_length(name, value, unit="mm")  -> Parameter
.ensure_length(name, value, unit="mm")  -> Parameter
.remove(name)
len(...) / iter(...) / name in ...
```

### Parameter

```python
.name        # CATIA가 준 값. 정규화될 수 있음
.short_name  # 마지막 "\" 뒤
.kind        # "Length"
.value
.unit        # Length면 "mm", 그 외 None
.set(value, unit="mm")
.info()      -> ParameterInfo(name, short_name, kind, value, unit)
```

### SketchCollection / Sketch / SketchEditor

```python
part.sketches.count / .list() / .names() / .get(name)
             .create(name, support="XY")   -> Sketch
             .ensure(name, support="XY")   -> Sketch
             .remove(name)

sketch.name / .rename(name) / .support() / .axis_data() / .element_names()
      .set_center_line(line)          # Shaft / Groove용 회전축
      .constraints -> ConstraintCollection

with sketch.edit() as editor:
    editor.point(x, y)
    editor.line(x1, y1, x2, y2)
    editor.circle(cx, cy, radius)
    editor.arc(cx, cy, radius, start_param, end_param)
    editor.spline([(x1, y1), (x2, y2), (x3, y3)])
    editor.set_construction(element, True)
    editor.rectangle(width, height, origin_x=0.0, origin_y=0.0)
    # 제약 — edit() 안에서만 유효하다
    editor.horizontal(line) / .vertical(line)
    editor.perpendicular(a, b) / .parallel(a, b)
    editor.coincident(a, b) / .tangent(a, b)
    editor.concentric(circle_a, circle_b)
    editor.length(line, value=None, unit="mm")     -> Constraint
    editor.radius(circle, value=None, unit="mm")   -> Constraint
    editor.distance(a, b, value=None, unit="mm")   -> Constraint
```

### ConstraintCollection / Constraint

```python
sketch.constraints.count / .list() / .names() / .get(name)
                  .broken_count / .unupdated_count
len(...) / iter(...) / name in ...

constraint.name / .type_code / .status        # status 0이 정상
          .value                              # 치수 제약이 아니면 None
          .set_value(value, unit="mm")
          .dimension_parameter() -> Parameter # formula 대상
```

`support`는 `"XY"`, `"YZ"`, `"ZX"` 중 하나다.

### PartDesign / Pad / Pocket

```python
part.part_design.pads / .pockets / .shafts / .grooves / .mirrors
                .get_pad(name) / .get_pocket(name) / .get_shaft(name)
                .get_groove(name) / .get_mirror(name)
                .create_pad(name, sketch, height, unit="mm")
                .create_pocket(name, sketch, depth, unit="mm")
                 .create_shaft(name, sketch)        # 스케치에 축 필요
                 .create_groove(name, sketch)
                 .create_mirror(name, support="YZ")
                 .create_rectangular_pattern(
                     pad, 2, 1, 60, 60, direction_1="X", direction_2="Y"
                 )
                 .ensure_*(...)   /  .remove_*(name)

# Pad와 Pocket은 SketchFeature를 공유한다
feature.name / .depth / .set_depth(depth, unit="mm") / .sketch()
        .depth_parameter()   -> Parameter   # formula가 구동할 대상
pad.height / pad.set_height(height, unit="mm")   # depth의 별칭

# Shaft와 Groove는 RevolvedFeature를 공유한다 (FirstLimit이 아니라 FirstAngle)
revolve.first_angle / .second_angle                 # 도 단위, 기본 360 / 0
        .set_first_angle(angle, unit="deg") / .set_second_angle(...)
        .sketch() / .first_angle_parameter()

# Mirror는 평면에서 만들어지므로 sketch()가 없다
mirror.name

# RectangularPattern은 생성과 반환 객체 기반 삭제만 노출한다.
# 이름 기반 조회/ensure/mutation은 검증하지 않았다.
# signed axis의 sign이 유일한 방향 선택이며 별도 reverse flag는 없다.
pattern.com_object
```

### Sketch 축 지정

```python
with sketch.edit() as editor:
    editor.rectangle(10, 6, origin_x=20)   # 축에서 떨어진 프로파일
    axis = editor.line(0, 0, 0, 20)
sketch.set_center_line(axis)               # Shaft / Groove에 필요
```

### FormulaCollection / Formula

```python
part.formulas.count / .list() / .names() / .get(name)
             .relation_name(parameter)    -> str   # 수식 본문에 쓸 이름
             .create(name, target, body, comment="") -> Formula
             .ensure(name, target, body, comment="") -> Formula
             .remove(name)
len(...) / iter(...) / name in ...

formula.name / .body / .comment / .activated / .input_count
       .modify(body) / .rename(name) / .activate() / .deactivate()
```

### 예외

전부 `Auto3dxError`를 상속한다. `pywintypes.com_error`는 라이브러리 밖으로 나오지 않는다.

```text
Com3dxNotFoundError        com3dx.py 헬퍼를 못 찾음
CatiaConnectionError       세션 attach 실패
NoActiveEditorError        열린 editor 없음
NoActivePartError          현재 편집 대상이 Part가 아님 (Assembly 등)
ParameterNotFoundError     이름으로 파라미터를 못 찾음
ParameterNameError         쓸 수 없는 이름 (빈 문자열, "\" 포함 등)
ParameterAlreadyExistsError  이미 있는 이름으로 생성 시도
ParameterTypeError         지원하지 않는 파라미터 타입 / 값 타입
UnsupportedUnitError       지원하지 않는 단위
PartUpdateError            Part.Update() 실패
SketchNotFoundError        이름으로 스케치를 못 찾음
SketchAlreadyExistsError   이미 있는 이름으로 생성 시도
SketchSupportMismatchError 같은 이름인데 다른 평면
FeatureNotFoundError       이름으로 feature를 못 찾음
FeatureConflictError       같은 이름인데 다른 스케치 기반
UnsupportedSupportError    "XY"/"YZ"/"ZX" 외의 평면 문자열
FormulaNotFoundError       이름으로 formula를 못 찾음
FormulaAlreadyExistsError  이미 있는 이름으로 생성 시도
AmbiguousNameError         같은 이름이 둘 이상
PartialCreationError       생성은 됐는데 이름 지정이 실패 (모델에 흔적 남음)
```

---

## 5. 할 수 없는 것과 그 이유

### 5.1 Part 생성 — 계정 제약

```text
PLMNewService.PLMCreate('VPMReference')  ->  [Licensing] Operation not authorized
```

이 계정에서는 **Automation으로 PLM 객체를 만들 수 없다.** UI에서는 만들어지므로 role
권한 문제가 아니라 Automation 경로의 라이선스 제약이다. 인자(`'VPMReference'`,
`'3DShape'`, `V_Name`)는 맞다는 것까지 확인했고, `SetAttributeValue`는 통과한다.
자세한 내용과 재개 절차는 `docs/plm_object_creation.md`에 있다.

따라서 Part 생성은 사람이 UI에서 한다.

### 5.2 Relations 중 formula 외의 것 — 미구현

`Relations`는 formula 말고도 `CreateLaw`, `CreateDesignTable`, `CreateCheck`,
`CreateProgram`, `CreateRuleBase`, `CreateSetOfEquations`를 노출하지만 전부 미검증이다.
formula만 구현되어 있다 (3.5 참조).

### 5.3 여러 Part 동시 작업 — 지원

`ActiveEditor`가 UI 탭 전환을 즉시 따라오지 않는 실제 문제가 있어, `editors()` / `parts()` /
`part_named(name)`을 제공한다. 변경할 Part는 `part_named()`로 명시적으로 고르는 편이 안전하고,
반환된 각 Part는 자기 editor의 Selection과 measurement service를 사용한다.

### 5.4 스레드

메인 스레드 전용이다. worker thread에서 쓰려면 각 스레드의 COM 초기화
(`pythoncom.CoInitialize()`)가 필요한데 검증하지 않았다. `com3dx` 모듈 로딩 자체는
lock으로 직렬화되어 있어 중복 로딩은 일어나지 않는다.

---

## 6. 안전 규칙

라이브러리가 지키는 규칙이다.

1. **어떤 경로에서도 `Save()` / `PLMPropagate()`를 호출하지 않는다.** 테스트로 고정되어
   있어 `Part.Save`가 호출되면 테스트가 실패한다. 저장은 사람이 UI에서 한다.
2. `set()` / `create_*` / `ensure_*`는 `Part.Update()`를 자동 호출하지 않는다. 여러 값을
   바꾼 뒤 update를 한 번만 부를 수 있게 하기 위해서다.
3. 검증되지 않은 COM API는 호출하지 않는다.
4. `pywintypes.com_error`는 경계에서 전부 `Auto3dxError` 계열로 변환한다.
5. 이름 충돌은 조용히 넘어가지 않는다. CATIA는 중복 이름을 허용하지만 라이브러리는
   거부한다.

---

## 7. 확장 순서 제안

1. **모서리 선택 레이어** — `Selection.Search('Topology.Edge,all')`은 열렸지만 모델 재빌드
   뒤에도 같은 모서리를 재선택하는 안전한 selector가 아직 없다. probe 31 실측에서
   변경 전 반복 검색은 안정적이었지만 Pad 높이 update 뒤 edge 수가 20→29로 바뀌고
   BRep name multiset과 검색 순서가 모두 달라졌다. raw 이름과 index는 selector로 쓸 수
   없고, `MeasurableService` 경로도 edge 길이를 노출하지 않았다.
2. **Chamfer 인자 확정** — Edge Reference는 확보했지만 mode/orientation 정수의 뜻이 미확정이다.
3. **사용자 정의 평면** — offset plane 스케치는 되지만 Pad와의 결합이 막혀 있다.
4. **Stiffener / CircPattern 등** — 생성 성공 뒤 update가 실패한 기능은 다시 probe로 검증해야 한다.

각 항목은 probe로 실제 동작을 확인한 뒤 라이브러리에 올린다. 기존 probe가 그 절차의
예시다.
