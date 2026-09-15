# auto-3dx 기능 현황

이 문서는 **실제로 동작이 확인된 것만** 적는다. 검증 근거는 `scripts/probes/`의 probe와
`tests/integration/`의 통합 테스트다. 라이브 통합 테스트는 실행 중인 3DEXPERIENCE 세션이
없으면 skip되므로, 과거 probe의 성공과 현재 테스트 실행 결과를 구분해서 기록한다.

- 대상 설치본: B428_Cloud
- 실행 환경: 표준 CPython 3.14.2 venv와 Conda `auto-3dx` env(Python 3.11.16), 둘 다 64-bit,
  pywin32 312. 두 환경 모두 unit과 live integration을 통과했다(README "검증된 Python 환경")
- 현재 정적 검증: **861 unit 통과**
- 현재 라이브 검증: 이번 세션의 아키텍처 변경 이후 2026-09-15 재실행 기준 **38 integration
  통과, 1건 skip**(그 1건은 열려 있는 Part에 수동으로 파라미터를 추가해야 통과한다). 실행 뒤
  모델이 실행 전 상태와 같았다

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
                      (원점 평면 또는 offset/각도 평면 위)
                   -> 패드 / 포켓 / 회전 / Rib·Slot / 사각 패턴 생성
                   -> 모서리 필렛 / 챔퍼, Shell / Thickness / Hole 생성
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
| **사용자 정의 평면(offset/각도) 위 스케치** | 동작 | `part.planes`로 평면을 만들어 스케치. Pad까지 검증 (3.3.1) |

### 3.3.1 사용자 정의 평면 (Offset / Angle)

원점 평면(`XY`/`YZ`/`ZX`) 3개 문자열은 그대로 쓸 수 있고, 이제 `part.planes`
(`PlaneCollection`)로 그 위에 offset 평면과 각도 평면도 만들 수 있다.

```python
plane = part.planes.create_offset("TOP_OFFSET", support="XY", offset=30)
sketch = part.sketches.create("TOP_SKETCH", support=plane)

angled = part.planes.create_angle(
    "TILTED", support="XY", angle=45,
    axis_start=(0, 0, 0), axis_end=(0, 0, 10),
)
```

- 각도 평면은 회전축으로 **주소 지정 가능한 3D 선**이 필요하다. 스케치 안의 2D 선이나
  원점 평면 자체는 생성은 되지만 `Part.Update()`가 실패하므로, 라이브러리가 내부에서
  점 2개(`axis_start`/`axis_end`) + 선 1개를 따로 만들어 축으로 쓴다.
- 이 컬렉션이 만드는 평면은 전부 하나의 기하 세트(`HybridBody`, 이름
  `auto_3dx_Planes`)에 들어간다. 평면·축 점·축 선을 개별 세트로 나누지 않는다.
- `remove(plane)`은 평면 하나만 지운다. 각도 평면의 축 점 2개와 축 선은 그대로 남는다.
  이것까지 함께 지우려면 `remove_geometrical_set()`으로 이 컬렉션이 만든 것 전부를
  지워야 한다.
- `ensure_offset`/`ensure_angle`은 없다. `HybridShapes`를 `Count`/`Item(i)`로 순회해
  이름과 타입을 읽는 것은 probe 38에서 live로 확인됐지만(2026-09-15, conventions 1.5),
  이름으로 다시 찾은 평면이 요청과 같은지 비교하는 `ensure`는 아직 만들지 않았다.
  재사용이 필요하면 호출자가 반환된 `Plane` 객체를 직접 들고 있어야 한다.
- `sketches.ensure(name, support=...)`의 `support`는 여전히 원점 평면 문자열 3개만
  받는다. offset/각도 평면 위 스케치의 재사용 여부는 `create()`로 직접 관리해야 한다.

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
| **모서리 필렛 생성 / 조회 / 삭제** | 동작 | `create_edge_fillet`. `part.topology.edges()`의 `Edge`만 받는다 (3.4.2) |
| **챔퍼 생성 / 조회 / 삭제** | 동작 | `create_chamfer`. mode는 내부 고정값 1, 인자로 노출 안 함 (3.4.2) |
| **Shell 생성 / 조회 / 삭제** | 동작 | `create_shell`. `part.topology.faces()`의 `Face`만 받는다 (3.4.3) |
| **Thickness 생성 / 조회 / 삭제** | 동작 | `create_thickness`. `Face`만 받는다 (3.4.3) |
| **Hole 생성 / 조회 / 삭제** | 동작 | `create_hole`. `Face`만 받는다 (3.4.3) |
| 목록 / 이름 조회 | 동작 | `pads`~`slots`에 `edge_fillets`, `chamfers`, `shells`, `thicknesses`, `holes` 추가 |
| formula 대상 파라미터 얻기 | 동작 | `depth_parameter()` / `first_angle_parameter()` |
| **그 외 전부** | **불가** | 아래 참고 |

삭제 시 주의 (실측으로 확인된 비대칭):

```text
패드 삭제   -> 그 스케치까지 연쇄 삭제됨
포켓 삭제   -> 스케치는 남는다. 따로 지워야 한다
```

`ShapeFactory`는 `AddNew*` 메서드를 **90개** 노출한다. 그중 구현된 것은 `AddNewPad`,
`AddNewPocket`, `AddNewShaft`, `AddNewGroove`, `AddNewMirror`, `AddNewRib`, `AddNewSlot`,
`AddNewRectPattern`, `AddNewEdgeFilletWithConstantRadius`, `AddNewChamfer`, `AddNewShell`,
`AddNewThickness`, `AddNewHole` **13개**다.

면·모서리를 지목할 수 없어 막혀 있던 약 80개 중 처음 다섯 개(EdgeFillet, Chamfer, Shell,
Thickness, Hole)가 뚫렸다. `Selection.Search('Topology.Edge,all')` /
`('Topology.Face,all')` + `SelectedElement.Reference`라는 모서리·면 참조 경로 하나가
그 다섯을 가능하게 했지 범용 참조 레이어가 아니다. `Draft`처럼 남은 면 참조 factory는
아직 시험하지 않았다.

나머지가 막힌 이유는 두 가지다.

```text
모서리·면 참조로 해결됨     EdgeFillet, Chamfer, Shell, Thickness, Hole
                            -> Selection.Search + SelectedElement.Reference로 모서리
                               또는 면 Reference를 얻어 넘긴다. 단, 그 Reference로 나중에
                               같은 모서리·면을 다시 지목할 방법은 없다 (아래 3.4.2/3.4.3).
생성은 되는데 update 실패    Stiffener, CircPattern
                            -> 객체는 트리에 생기지만 모델이 재계산에 실패한다.
                               "생성 성공"을 검증으로 쳐주지 않는 이유다.
```

미구현 예:

```text
AddNewDraft       AddNewStiffener   AddNewCircPattern AddNewUserPattern
AddNewLoft        AddNewSplit       AddNewTrim        AddNewSolidCombine ... 외 69개
```

### 3.4.1 스케치 제약

**제약은 `sketch.edit()` 안에서만 걸린다.** 편집 세션이 닫힌 뒤에는 전부 실패한다. 그래서
생성 메서드는 `SketchEditor`에만 있다 — 위치가 곧 계약이다.

인자는 `line()` / `circle()`이 돌려준 **`SketchElement`를 그대로** 넘긴다. SDK가 그 안의 2D
COM 객체를 꺼내 CATIA에 전달하고, 다른 스케치에서 그린 요소는 COM 호출 전에 `ValidationError`로
거부한다. Part Design과 달리 CATIA는 `Reference`로 감싼 인자를 거부하므로 SDK도 감싸지 않는다.

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

### 3.4.2 모서리 필렛과 챔퍼

면·모서리를 지목할 방법이 없어 막혀 있던 약 80개 feature 중 처음 두 개다. 이 둘 때문에
새 참조 레이어(`geometry.edges`)가 생겼다.

```python
snapshot = part.topology.edges()   # 솔리드 전체 모서리, EdgeSnapshot
fillet = part.part_design.create_edge_fillet("F1", snapshot[0], radius=3)
part.update()

chamfer = part.part_design.create_chamfer(
    "C1", snapshot[1], length1=1.5, length2_or_angle=45,
    propagation=0, orientation=0,
)
part.update()
```

세 가지 제약을 반드시 알아야 한다.

- **`part.topology.edges()`는 솔리드 전체를 검색한다.** 한 feature의 모서리만 골라 검색
  범위를 좁히는 방법이 없다(네 가지 경로를 시험했고 전부 막혔다). 필요한 모서리는
  호출자가 `EdgeSnapshot`을 순회하며 스스로 걸러야 한다.
- **모서리를 안정적으로 다시 지목할 방법이 없다.** `Edge.descriptor`는 BRep 이름 문자열을
  주지만 저장했다가 나중에 다시 그 모서리로 되돌리는 경로가 전부 막혔고, 재빌드가 일어나면
  모서리 개수와 순서(그리고 `Edge.index`)가 전부 바뀐다. 그래서 `part.topology.edges()`를 다시
  부르는 것 외에는 답이 없다.
- **모델이 바뀌면 이전 snapshot은 거부된다.** 같은 snapshot으로 필렛을 두 번 만들면
  성공할 때도 실패할 때도 있고, 호출자는 어느 쪽인지 미리 알 수 없다. 그래서 CATIA Part
  하나에 model generation 카운터가 하나 있고, 그 Part로부터 얻은 모든 collection과 wrapper가
  같은 카운터를 공유한다. `active_part()`를 다시 부르거나 `part_named()`, 다른
  `Catia.attach()`로 얻은 wrapper도 COM 동일성(`==`)으로 같은 Part면 같은 카운터를 쓴다. feature 생성·삭제·이름변경, 파라미터·제약 값 쓰기, formula
  변경, `sketch.edit()` 세션을 닫는 것, `part.update()`(성공/실패 무관) 등 COM에
  mutation을 시도하는 모든 경로가 카운터를 올리고, 읽기와 COM 전에 거부된 요청은 올리지
  않는다. 파라미터 값은 그 파라미터가 아무것도 구동하지 않아도 카운터를 올린다. 이
  카운터가 스냅샷을 뜬 시점보다 올라가 있으면 그 스냅샷의 `Edge`를 쓰는 순간 COM에 닿기
  전에 `StaleSnapshotError`를 낸다. CATIA UI나 다른 스크립트로 만든 변경은 이 카운터에
  보이지 않으므로, 새 작업 전에는 항상 새 `part.topology.edges()`를 불러야 한다.

그 외:

- 챔퍼의 `mode`는 인자로 노출하지 않는다. 세 값 중 1만 생성과 update 모두 성공해서
  내부에 고정했다(0은 update 실패, 2는 생성 자체가 실패). `propagation`/`orientation`은
  정수 뜻이 문서화되어 있지 않아 검증된 값만 상수로 남겼다.
- `ensure_edge_fillet`/`ensure_chamfer`는 없다. `ensure_pad`처럼 기존 feature의 소스를
  비교하려면 안정적으로 다시 읽을 수 있는 핸들이 필요한데, 모서리에는 그런 핸들이 없다.
  잘못된 모서리를 조용히 재사용하는 것보다 메서드가 없는 편이 낫다.
- 필렛/챔퍼 모두 `create_*` 뒤 update가 실패하면 그 feature가 트리에 남고, **지우기 전까지
  이후의 모든 `Part.Update()`가 실패한다.** `remove_edge_fillet(name)`/`remove_chamfer(name)`
  으로 지운 뒤에 재시도해야 한다.

### 3.4.3 Shell, Thickness, Hole (면 참조)

모서리와 같은 참조 경로가 면에도 통한다. `part.topology.faces()`가 돌려주는
`FaceSnapshot`에서 `Face`를 얻어 `create_shell`/`create_thickness`/`create_hole`에
넘긴다.

```python
faces = part.topology.faces()   # 솔리드 전체 면, FaceSnapshot

shell = part.part_design.create_shell(
    "S1", faces[0], internal_thickness=2.0, external_thickness=0.0
)
part.update()

thickness = part.part_design.create_thickness("T1", faces[1], offset=3.0)
part.update()

hole = part.part_design.create_hole("H1", faces[2], depth=5.0)
part.update()
```

검증된 값은 shell `(internal_thickness=2.0, external_thickness=0.0)`, thickness
`offset=3.0`, hole `depth=5.0`이고, 각각 첫 면 하나에서 생성 + `Part.Update()`를
확인했다(probe 37). `internal_thickness`/`offset`/`depth`는 유한하고 양수만 받고,
`external_thickness`만 검증된 경계값이 `0.0`이라 0 이상을 허용한다.

- **모서리와 같은 model generation을 공유한다.** 모델이 바뀌면 이전 `FaceSnapshot`의
  `Face`는 COM 전에 `StaleSnapshotError`로 거부된다.
- **다만 재사용 실패는 모서리만큼 반복 검증하지 않았다.** 모서리는 같은 snapshot의
  다음·중간·마지막 모서리를 전부 시험해 실패를 확인했지만, 면은 feature마다 새 검색으로
  한 번씩만 확인했다. 같은 `Reference` 메커니즘이라 같은 규칙을 보수적 기본값으로 적용한
  것이지, 면에 대해 재사용 실패를 실제로 재현한 결과는 아니다.
- `ensure_shell`/`ensure_thickness`/`ensure_hole`은 없다. 모서리와 같은 이유로, 면에는
  기존 feature와 비교할 안정적인 핸들이 없다.
- 생성 뒤 update가 실패하면 그 feature가 트리에 남고, 지우기 전까지 이후의 모든
  `Part.Update()`가 실패한다. `remove_shell`/`remove_thickness`/`remove_hole`으로 지운
  뒤에 재시도해야 한다.

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
| **솔리드 측정** | 동작 | `part.measurement`로 부피·면적·질량·무게중심 조회. bounding box는 제공 안 함 |

### 3.7 손대지 않은 영역

`Part`가 노출하지만 라이브러리가 쓰지 않는 것:

```text
HybridShapeFactory     평면(AddNewPlaneOffset/AddNewPlaneAngle)과 그 축용 점/선만 사용.
                       그 외 GSD surface geometry는 쓰지 않음
Bodies / HybridBodies  MainBody 외 body. HybridBodies는 평면을 담는 기하 세트 하나(3.3.1)에만 사용
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
.planes          -> PlaneCollection   # offset/각도 평면
.formulas        -> FormulaCollection
.update()        # 실패 시 PartUpdateError
.measurement     -> SolidMeasurement  # editor 기반 read-only 측정
```

### SolidMeasurement / 측정 결과

```python
part.measurement.measure() -> MassProperties            # Part의 main body (기본값)
part.measurement.measure(part.com_object.MainBody)      # raw 대상도 여전히 받는다

MassProperties(
    volume_mm3, area_mm2, mass_kg, cog_mm=(x, y, z)
)
```

기본 대상은 생성 시점이 아니라 측정 시점마다 다시 읽는다. 기본 대상도 없는데 인자도
없으면 COM 호출 전에 `ValidationError`다. `SolidMeasurement.com_object`가 다른 wrapper와
같은 이름의 escape hatch이고, `editor_com_object`는 `DeprecationWarning`을 내는 alias로
1.0 전에 제거한다.

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
             # support는 "XY"/"YZ"/"ZX" 문자열이거나
             # part.planes가 만든 OffsetPlane/AnglePlane
             .ensure(name, support="XY")   -> Sketch
             # ensure의 support는 원점 평면 문자열만 받는다 (아래)
             .remove(name)

sketch.name / .rename(name) / .support() / .axis_data() / .element_names()
      .set_center_line(line)          # Shaft / Groove용 회전축
      .constraints -> ConstraintCollection

with sketch.edit() as editor:
    editor.point(x, y)                                  -> SketchElement
    editor.line(x1, y1, x2, y2)                         -> SketchElement
    editor.circle(cx, cy, radius)                       -> SketchElement
    editor.arc(cx, cy, radius, start_param, end_param)  -> SketchElement
    editor.spline([(x1, y1), (x2, y2), (x3, y3)])       -> SketchElement
    editor.set_construction(element, True)
    editor.rectangle(width, height, origin_x=0.0, origin_y=0.0)  -> list[SketchElement]
    # SketchElement: .com_object(raw 2D 객체) / .kind("Line2D" 등)
    # geometry 읽기(반지름, 좌표)는 제공하지 않는다. 필요하면 com_object로 읽는다.
    # 다른 스케치에서 그린 요소를 넘기면 COM 전에 ValidationError. raw 객체도 받는다.
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

### PartDesign / 모서리 필렛 / 챔퍼

```python
part.topology.edges()  -> EdgeSnapshot   # 솔리드 전체, 모델이 바뀌면 stale
part.topology.faces()  -> FaceSnapshot   # 같은 규칙
# part.part_design.snapshot_edges() / snapshot_faces()는 deprecated alias다.
# 경고를 내고 같은 generation을 공유하며, 1.0 전에 제거한다.
                .edge_fillets / .chamfers
                .get_edge_fillet(name) / .get_chamfer(name)
                .create_edge_fillet(name, edge, radius, unit="mm",
                                     propagation=EDGE_FILLET_PROPAGATION_VERIFIED)
                .create_chamfer(name, edge, length1, length2_or_angle,
                                 propagation, orientation, unit="mm")
                .remove_edge_fillet(name) / .remove_chamfer(name)

edge_snapshot[i] / len(edge_snapshot) / iter(edge_snapshot)  -> Edge
edge.com_object / edge.index / edge.descriptor   # index/descriptor는 이 snapshot 안에서만 유효

# ensure_edge_fillet / ensure_chamfer 없음. edge에는 재사용 가능 여부를
# 안전하게 비교할 핸들이 없다.
# propagation/orientation은 검증된 정수만 상수로 제공된다. mode는 노출하지 않는다
# (내부에서 항상 1).
```

### PartDesign / Shell / Thickness / Hole

```python
                .shells / .thicknesses / .holes
                .get_shell(name) / .get_thickness(name) / .get_hole(name)
                .create_shell(name, face, internal_thickness, external_thickness,
                               unit="mm")
                .create_thickness(name, face, offset, unit="mm")
                .create_hole(name, face, depth, unit="mm")
                .remove_shell(name) / .remove_thickness(name) / .remove_hole(name)

face_snapshot[i] / len(face_snapshot) / iter(face_snapshot)  -> Face
face.com_object / face.index / face.descriptor   # index/descriptor는 이 snapshot 안에서만 유효

# ensure_shell / ensure_thickness / ensure_hole 없음. 이유는 edge와 같다.
# internal_thickness/offset/depth는 양수만 받는다. external_thickness만
# 검증된 경계값이 0.0이라 0 이상을 허용한다.
```

### PlaneCollection / OffsetPlane / AnglePlane

```python
part.planes.create_offset(name, support, offset, orientation=False) -> OffsetPlane
           .create_angle(name, support, angle, axis_start, axis_end,
                          orientation=False) -> AnglePlane
           .remove(plane)                 # 평면 하나만
           .remove_geometrical_set()      # 이 컬렉션이 만든 전부(축 점·선 포함)

plane.com_object / plane.name / plane.base_display_name
offset_plane.offset     # OffsetPlane 전용
angle_plane.angle       # AnglePlane 전용

# ensure_offset / ensure_angle 없음. support는 "XY"/"YZ"/"ZX" 또는
# 이 컬렉션이 이미 만든 Plane.
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
다섯 범주는 "호출자가 그 뒤에 무엇을 할 수 있는가"로 나뉜다. 반응이 같으면 범주를,
다르면 구체 클래스를 잡는다.

```text
Auto3dxError
├── SessionError             세션에 닿지 못함. 모델은 손대지 않았다
│   ├── Com3dxNotFoundError        com3dx.py 헬퍼를 못 찾음
│   ├── CatiaConnectionError       세션 attach 실패
│   ├── NoActiveEditorError        열린 editor 없음
│   └── NoActivePartError          현재 편집 대상이 Part가 아님 (Assembly 등)
├── ValidationError          COM 호출 전에 거부됨. 모델은 그대로다
│   ├── ParameterNameError         쓸 수 없는 이름 (빈 문자열, "\" 포함 등)
│   ├── ParameterTypeError         지원하지 않는 파라미터/값 타입, 또는 edge·radius 등
│   │                              파라미터가 아닌 인자 (이름 부채, 8절 참고)
│   ├── UnsupportedUnitError       지원하지 않는 단위
│   ├── UnsupportedMagnitudeError  CreateDimension의 magnitude가 단위 카탈로그에 없음
│   ├── UnsupportedSupportError    "XY"/"YZ"/"ZX" 외의 평면 문자열
│   └── StaleSnapshotError         모델이 바뀐 뒤 옛 EdgeSnapshot/FaceSnapshot의
│                                  Edge/Face를 사용
├── NotFoundError            그 이름의 객체가 없음 (열거로 확인, 실패한 조회로 추정하지 않음)
│   ├── ParameterNotFoundError     이름으로 파라미터를 못 찾음
│   ├── SketchNotFoundError        이름으로 스케치를 못 찾음
│   ├── FeatureNotFoundError       이름으로 feature를 못 찾음
│   ├── FormulaNotFoundError       이름으로 formula를 못 찾음
│   └── ConstraintNotFoundError    이름으로 제약을 못 찾음
├── ConflictError            모델의 이름·상태가 요청을 막음. 아무것도 만들지 않았다
│   ├── ParameterAlreadyExistsError  이미 있는 이름으로 생성 시도
│   ├── SketchAlreadyExistsError     이미 있는 이름으로 생성 시도
│   ├── FormulaAlreadyExistsError    이미 있는 이름으로 생성 시도
│   ├── FeatureConflictError         같은 이름인데 다른 스케치 기반, 또는 패턴 방향이 같은 축
│   ├── SketchSupportMismatchError   같은 이름인데 다른 평면
│   └── AmbiguousNameError           같은 이름이 둘 이상
└── AutomationError          CATIA가 COM 호출을 거부하거나 실패함. hresult 속성을 가짐
    ├── PartUpdateError            Part.Update() 실패
    └── PartialCreationError       생성은 됐는데 이름 지정이 실패 (모델에 흔적 남음)
```

`ValidationError`는 COM에 닿기 전에 거부됐다는, 즉 모델이 안 바뀌었다는 보장을 준다.
`AutomationError`는 COM 호출이 실제로 시도됐다는 뜻이라 모델이 바뀌었을 수 있고, 원본
`pywintypes.com_error`를 `__cause__`로 chain한다. `PartUpdateError`와
`StaleSnapshotError`는 흔히 개별로 잡을 만해서 `Auto3dxError`, `SessionError`,
`ValidationError`, `NotFoundError`, `ConflictError`, `AutomationError`와 함께
`Catia`/`Part`만 있는 패키지 루트에서도 바로 import할 수 있다. 나머지 구체 클래스는
`auto_3dx.errors`에서 가져온다.

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

완료: 모서리·면 선택 레이어(`part.topology.edges()`/`faces()`, `EdgeSnapshot`/
`FaceSnapshot`), Chamfer 인자 확정(mode=1 고정), Shell/Thickness/Hole(면 참조),
사용자 정의 offset/각도 평면(스케치 + Pad까지 검증), Part당 하나의 공유 model
generation, 예외 다섯 범주, 작은 패키지 루트, 측정 기본 대상(main body), topology 검색 전후의
사용자 selection 복원(`SelectionNotRestoredWarning`), 같은 CATIA Part의 wrapper끼리 공유하는
generation, `part.inspect.summary()`의 body·기하 세트·모서리와 면 개수. 이제 남은
순서는 다음과 같다.

1. **Stiffener / CircPattern 등** — 생성 성공 뒤 update가 실패한 기능은 다시 probe로
   검증해야 한다. 지금 기준으로는 미검증이며 구현하지 않는다.
2. **모서리·면 재선택 selector** — 지금은 재빌드마다 `part.topology.edges()`/`faces()`를
   새로 불러야 한다. BRep 이름 재해석, 재빌드 후 이름/순서 보존, 측정 기반 선택,
   feature 단위 검색 범위 한정 네 가지 경로를 모두 시험했고 전부 막혔다
   (`geometry.edges`). 새로운 돌파구가 없으면 이 항목은 열린 채로 남는다.

각 항목은 probe로 실제 동작을 확인한 뒤 라이브러리에 올린다. 기존 probe가 그 절차의
예시다.
