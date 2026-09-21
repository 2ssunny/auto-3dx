# auto-3dx 진행 상황과 미해결 문제

이 문서는 **지금 어디까지 왔고, 무엇이 왜 막혀 있는지**를 기록한다.

관련 문서:

| 문서 | 내용 |
|---|---|
| `docs/capabilities.md` | 기능별로 무엇이 되고 안 되는지 |
| `docs/conventions.md` | 실측한 COM 사실과 코드 계약 |
| `docs/plm_object_creation.md` | Part 생성이 막힌 경위 상세 |
| 이 문서 | 전체 상황, 미해결 문제, 결정 기록 |

- 대상 설치본: B428_Cloud / 3DSpace `Andrew_Test`
- 실행 환경: 표준 CPython 3.14.2 venv와 Conda `auto-3dx` env(Python 3.11.16), 둘 다 64-bit,
  pywin32 312. Conda는 필요하지 않다. unit은 표준 CPython에서 896 통과. live integration은 표준 CPython에서 42 통과(스케치 support
  판정 추가 후), Conda에서 38 통과·1 skip(그 전),
  실행 뒤 기준 모델 동일(2026-09-15). GitHub Actions Windows CPython 3.11–3.14에서 unit 통과(3.12는
  CI unit으로만 확인, live 미실행)
- 테스트: **1156 unit 통과**. 2026-09-21 Phase 4(기하 사실 측정·의미 기반 쿼리·방향·평면 편집·update 진단) 뒤
  빈 테스트 Part `3D Shape00422558`에서 integration **62 통과, 6 skip**, A→B
  acceptance(`phase4_geometry.py`)와 Phase 1–3 acceptance 재실행 통과, 실행 뒤 기준 상태와 같음. 그 전 기록: **1089 unit 통과**. 2026-09-19 Phase 3(원형 패턴·boolean·제약 삭제·feature 억제) 뒤
  빈 테스트 Part `3D Shape00422558`에서 integration **56 통과, 6 skip**, A→B
  acceptance(`phase3_operations.py`) 통과, 실행 뒤 기준 상태와 같음. 그 전 기록: **1036 unit 통과**. 2026-09-18 Phase 2(기존 모델 편집) 뒤 빈 테스트 Part
  `3D Shape00422558`에서 integration **49 통과, 6 skip**, A→B acceptance(`phase2_editing.py`)
  통과, 실행 뒤 기준 상태와 같음. 그 전 기록: **991 unit 통과**. 2026-09-18 첫 안전 배치 뒤 빈 테스트 Part `3D Shape00422558`에서
  integration **44 통과, 6 skip**, A→B acceptance(`batch1_safety.py`) 통과, 실행 뒤 기준 상태와 같음.
  그 전 기록: **957 unit 통과**. 2026-09-17 Multi-Body 뒤 빈 테스트 Part `AUTO3DX_MULTIBODY_TEST`에서
  integration **40 통과, 6 skip**(빈 main body·수동 파라미터가 필요한 테스트), 실행 뒤 기준 상태와 같음.
  그 전 기록: integration은 이번 세션의 아키텍처 변경(같은 Part의 wrapper끼리
  모델 generation 공유, 예외 범주 재편, 루트 축소, 측정 기본값, SketchElement, selection 복원,
  검사 필드 확장) 이후 2026-09-15에 live로 재실행해 **42 통과**(수동 파라미터가 없는 Part에서는 1건 skip)이고, 실행 뒤 모델이 기준
  상태와 같았다
- probe: `scripts/probes/`에 45개 존재
- 브랜치: `develop` (push·PR 안 함)

---

## 1. 한 눈에

```text
[사람]  3DEXPERIENCE UI에서 Part 생성        <- 막힘. 2.1
   |
[auto-3dx]  attach  (이름으로 Part 선택 가능)
            파라미터 생성 / 수정 / 삭제 (Length·Angle·Dimension·Real·Integer·String·Boolean)
            body 생성 / 작업 body 지정 / 숨김·표시 / 가드 삭제
            평면 생성 -> 원점 3개 + offset + 각도
            스케치 생성 -> 점·선·원·호·사각형·스플라인 (+ 회전축)
            스케치 제약 9종 + 반지름·동심
            패드 / 포켓 / Shaft / Groove / Mirror / Rib / Slot / 사각 패턴
            모서리 fillet / chamfer, Shell / Thickness / Hole
            formula로 치수·각도 연동
            부피·면적·질량·무게중심 측정
            update
   |
[사람]  결과 확인 후 직접 저장                <- 의도적으로 자동화 안 함. 4.1
```

**핵심 요약: 파트를 "만드는" 것과 "저장하는" 것만 빼고, 내용을 채우는 일은 자동화됐다.**

---

## 2. 미해결 문제

### 2.1 Part 생성이 불가능하다 — 계정/라이선스 제약 (최우선)

```text
PLMNewService.PLMCreate('VPMReference')  ->  [Licensing] Operation not authorized
PLMNewService.getLastError()             ->  ('', 0)
```

- **원인은 코드가 아니다.** 인자는 맞다. `SetAttributeValue('V_Name', ...)`는 통과하고,
  user type 문자열(`'VPMReference'`, `'3DShape'`)도 세션에 열려 있는 객체의
  `GetCustomType()`에서 확인했다.
- **role 권한 문제도 아니다.** 같은 계정으로 CATIA UI에서는 Physical Product가 만들어진다
  (실제로 `Physical Product00394025` 생성 성공).
- 따라서 **Automation 경로에만 걸린 라이선스 제약**이다. 세션 초반
  `UVD - Engineering Expert for Education` / `UVG - Program Manager for Education`
  확보에 실패한 이력이 있어 관련 가능성이 있다.
- `getLastError`가 빈 값이라 COM으로는 더 좁힐 수 없다.

**영향:** 실무상 크지 않다. 파트 생성은 프로젝트당 몇 번뿐이고, 반복 작업은 전부 그 다음
단계다. "UI로 만들고 auto-3dx로 채운다" 워크플로로 실제 동작을 확인했다.

**풀려면:** 라이선스 재확보 후 `scripts/probes/15_plm_create.py` 재실행. 상세는
`docs/plm_object_creation.md`.

### 2.2 Part Design 기능 — 참조 레이어가 뚫렸다

```text
ShapeFactory.AddNew* : 90개
구현됨               : Pad, Pocket, Shaft, Groove, Mirror, Rib, Slot, RectPattern,
                       모서리 fillet, chamfer, Shell, Thickness, Hole — 13개
```

**참조 레이어를 조사한 결과, 기대했던 "80개 일괄 해금"은 일어나지 않았다** (probe 17).

되는 것:

```text
Part.CreateReferenceFromObject(pad)  -> Reference (DisplayName = feature 이름)
Part.FindObjectByName(name)          -> Pad / Body / AnyObject(평면) 직접 획득
AddNewMirror(OriginElements.PlaneYZ) -> 동작. 평면은 주소 지정이 되므로 BRep 불필요
```

안 되는 것:

```text
AddNewEdgeFilletWithConstantRadius(pad, propagMode, r)  -> propagation mode 3종 모두 실패
AddNewChamfer(pad, ...)                                 -> 실패
```

즉 fillet/chamfer는 feature를 통째로 넘기는 것을 거부하고 **진짜 모서리 객체**를 요구한다.
그건 유효한 BRep 이름이 있어야 하고, BRep 이름은 모델이 바뀌면 깨진다.

막힌 이유는 API를 안 써서가 아니라 **인자로 넘길 면·모서리를 지목할 방법이 없어서**다.

```text
AddNewChamfer(iObjectToChamfer, ...)          <- "이 모서리"를 어떻게 지정하나
AddNewEdgeFilletWithConstantRadius(iEdgeToFillet, ...)
AddNewShell(iFaceToRemove, ...)
AddNewThickness(iFaceToThicken, ...)
AddNewDraft(iFaceToDraft, ...)
AddNewHole(iSupport, iDepth)
```

또 다른 부류는 **생성은 되는데 update가 실패**한다 (2.8 참조).

```text
AddNewStiffener(iSketch)   -> Stiffener 반환. Part.Update() 실패
AddNewRectPattern(...)     -> 방향 Reference 조합에 따라 생성 + Part.Update() 성공/실패
```

**2026-09-11 갱신 — 경로가 뚫렸다 (probe 28).** 위 문단은 `Selection`을 "사용자가 찍는 것"으로
전제했는데 그게 틀렸다. `Selection.Search`는 코드로 topology를 열거한다.

```text
Search('Topology.Edge,all')  -> 29개 (RectilinearTriDimFeatEdge)
Search('Topology.Face,all')  ->  9개 (PlanarFace)
Search('Edge,all') / ('Face,all')  -> COM 오류. 쿼리 문자열이 정확해야 한다
SelectedElement.Reference    -> Reference (CreateReferenceFromObject는 검색 결과에 실패)

AddNewEdgeFilletWithConstantRadius(모서리 Reference, 1, 반지름)
  -> 생성 + Part.Update() 성공. 면·모서리 feature 중 최초로 검증됨
```

probe 34·35에서 나머지가 풀렸다.

첫 fillet 이후의 실패는 두 가지가 겹친 것이었다. 하나는 **update가 한 번 실패하면 그 feature를
지우기 전까지 이후 update가 전부 실패한다**는 것이고, probe 28은 실패한 chamfer를 남긴 채
진행했다. 다른 하나는 stale reference가 실제로 문제라는 것이다. probe 34에서 같은 snapshot으로
2개를 만든 것이 통과했지만 그건 우연이었고, 평면 pad에서 다시 확인하니 다음·중간·마지막 모서리
전부 실패했다(둘은 생성, 하나는 update). 새 snapshot은 성공한다.

**되는지 안 되는지 예측할 수 없으므로** 라이브러리가 막는다. 이때는 `PartDesign`이 모델을
바꾸면 기존 edge snapshot이 stale이 되고, 이후 사용은 COM 전에 `StaleSnapshotError`가
된다는 규칙이었다. 이후 세션에서 이 추적을 `Part` 전체가 공유하는 하나의 model
generation으로 넓혔다 — 파라미터·스케치·평면·formula·제약·`update()`까지, `Part`로부터
닿는 모든 mutation 경로가 같은 카운터를 올린다 (`docs/api-design.md` 5절).

chamfer 인자도 확정했다. `iMode=1`만 동작한다(0은 update 실패, 2는 생성 실패). propagation과
orientation은 0·1 모두 통과한다.

**면도 같은 경로로 풀렸다 (probe 37).** fillet과 chamfer가 면을 거부한 건 그 둘이 모서리를
원해서지 면 참조가 안 돼서가 아니었다. `Search('Topology.Face,all')`로 얻은 면 Reference로
Shell·Thickness·Hole 세 개가 전부 첫 면에서 생성 + update를 통과했다.

**남은 한계는 "어느 모서리·어느 면인가"다.** 네 경로가 모두 막혔다.

```text
BRep 이름 저장 후 재해석   : CreateReferenceFromBRepName -> Part·Pad context 모두 실패
재빌드 후 이름·순서 보존   : pad 높이 하나 바꾸니 edge 20 -> 29개, 이름·순서 모두 달라짐
측정으로 기하 선택         : MeasurableService가 edge 길이를 노출하지 않음
검색 범위를 feature로 한정 : 'Topology.Edge,in,<이름>' 계열 전부 COM 오류
```

모델이 바뀌지 않는 동안에는 검색이 정확히 재현되므로(개수·이름·순서 동일, 2회 확인) index는
**그 시점의 모델 상태에서만** 유효하다. API는 이 한계를 숨기지 않고 드러내는 방식으로 만든다.

### 2.3 스케치 제약 — 해결됨

`Sketch.Constraints`로 제약을 직접 걸 수 있다. **편집 세션 안에서만** 동작하고 인자는 raw
2D 객체여야 한다(`Reference`는 거부). 그래서 제약 API는 `SketchEditor`에 있다. 치수 제약의
`Dimension`은 읽기·쓰기가 되므로 formula로 구동할 수 있다. 상세는 conventions 1.2.4.

호·스플라인·Construction 지정도 probe 27에서 생성 및 `Part.Update()` 성공을 확인했고,
현재 `SketchEditor.arc()` / `spline()` / `set_construction()`으로 노출한다. 서로 다른 두
`Circle2D`에 대한 동심 제약도 probe 27에서 생성 및 update 성공을 확인했고,
`SketchEditor.concentric()`으로 노출한다. 곡선 live integration도 현재 공개 adapter로
생성·update·cleanup까지 통과했다.

남은 제약: `Constraints.Remove(i)`는 호출해 본 적이 없어 제약 삭제는 구현하지 않았다.
`CatConstraintType`에 `Diameter`가 없어 지름 구속은 존재하지 않는다(반지름의 절반으로 쓴다).

### 2.4 Part 여러 개 동시 처리 — 해결됨

`Application.ActiveEditor`가 UI 탭 전환을 즉시 따라오지 않는 것을 실측했다 (탭은 새 파트인데
COM은 이전 파트를 가리킴). 엉뚱한 파트를 조용히 편집할 수 있는 문제였다.

`editors()` / `parts()` / `part_named(name)`으로 해결했다. 탭 상태와 무관하게 이름으로 고를
수 있고, 각 `Part`에는 그 editor 자신의 `Selection`이 연결된다. `ActiveObject`를 읽을 수
없는 editor가 섞여 있어도 열거가 죽지 않는다 (실측: 4개 중 1개가 그랬다).

### 2.5 파라미터 타입과 단위 — 대부분 해결됨

- 파라미터 타입: `Length`, `Angle`, 임의 magnitude의 `Dimension`, `Real`, `Integer`,
  `String`, `Boolean` 전부 지원한다.
- 단위: `parameters.units`(`UnitCatalogue`)로 339개 magnitude와 1887개 unit을 조회할 수
  있다. `parameter.magnitude`가 generic `Dimension`의 정체(Mass/Volume 등)를 알려준다.
- **단위 변환은 하지 않는다.** `Value`는 언제나 파라미터 자신의 내부 단위다. 단위 인자는
  "네가 의도한 단위가 맞는지" 확인하는 용도로만 쓰고, 다르면 거부한다. 변환을 검증한 적이
  없으므로 의도적으로 남겨둔 제약이다.

남은 제약:

- 스케치 평면: 원점 3개(XY/YZ/ZX)에 더해 `part.planes`로 만든 offset 평면과 각도 평면을
  `sketches.create(name, support=plane)`에 넘길 수 있다. 둘 다 pad까지 live로 검증했다
  (probe 36, conventions 1.2.7).
- 프로파일: 호·스플라인·점까지 probe 27에서 검증됐다. 곡선 프로파일도 pad 된다.

### 2.6 update 상태와 결과 검증 — rebuild 상태 + 측정으로 해결

`Part.IsUpToDate(iObject)`는 probe 32에서 feature-driven 상태 전이를 확인했다. Pad 높이를
바꾼 직후 Part/MainBody/Pad는 `False`, 영향받지 않은 Sketch는 `True`였고,
`Part.Update()` 후 모두 `True`가 됐다. 이를 `Part.is_up_to_date(target=None)`으로
노출한다. 단, 독립 사용자 Parameter 변경만으로는 Part/MainBody가 계속 `True`였으므로
저장되지 않은 모든 변경을 감지하는 API가 아니라 **feature rebuild 상태**로만 해석한다.

그런데 **결과를 직접 재는 쪽이 더 강한 검증**이고, 그게 probe 30에서 열렸다.
현재는 `Part.measurement`가 editor의 `InertiaService`를 감싸서 부피·면적·질량·무게중심을
읽는다. `InertiaBoxService`는 세션에 따라 조용히 0을 돌려주므로 제외했다(3절 #9).
값은 전부 SI(m, m², m³)이므로
public 결과에서 mm·mm²·mm³로 환산하고 질량은 kg로 유지한다. 측정 live integration도
현재 공개 adapter로 통과했고, 최초 live 동작 근거는 probe 30이다. 자세한 내용과 함정은
conventions 1.4 및 6.18에 있다.

### 2.8 `AddNew*` 성공이 feature 유효를 뜻하지 않는다

```text
AddNewStiffener(sketch)  -> Stiffener 반환. 이후 Part.Update() 실패
AddNewRectPattern(...)   -> 방향 인자가 틀리면 Part.Update() 실패
AddNewChamfer(edge)      -> Chamfer 반환. 이후 Part.Update() 실패
```

객체는 트리에 생겼는데 모델이 재계산에 실패한다. **생성 호출의 성공은 검증이 아니다.**

패턴 방향은 원점 평면으로 만든 `Reference`여야 하고, 어느 평면이 어느 축을 만드는지는
probe 30에서 측정으로 확정했다(conventions 1.2.5). 이에 따라 public API
`create_rectangular_pattern()`과 signed-axis 사전 검사가 구현됐고 unit 테스트가 있다.
생성 뒤 update가 실패하면 반환된 wrapper를
`remove_rectangular_pattern(pattern)`에 전달해 Selection으로 정리할 수 있다.
public wrapper 자체도 create → `Part.Update()` → 반환 객체 기반 Selection cleanup의
live integration을 통과했다. dir1과 dir2가 같은 축이 되면 COM 호출 전에 거부한다.

- probe의 "검증됨" 기준을 **생성 성공 + `Part.Update()` 성공**으로 정했다.
- 라이브러리의 `create_*`는 update를 호출하지 않으므로, 호출자가 update하고
  `PartUpdateError`를 처리해야 한다. **실패해도 feature는 모델에 남으므로** 호출자가 지운다.

### 2.7 스레드 안전성 미검증

메인 스레드 전용이다. worker thread에서 쓰려면 스레드별 COM 초기화
(`pythoncom.CoInitialize()`)가 필요한데 검증하지 않았다. `com3dx` 모듈 로딩만 lock으로
직렬화돼 있다.

---

## 3. 실측으로 드러난 함정

CATIA가 **조용히 넘어가는데 모델을 망가뜨리는** 동작들이다. 전부 라이브 세션에서 확인했고,
라이브러리가 막고 있으며 회귀 테스트로 고정돼 있다.

| # | CATIA의 동작 | 결과 | 라이브러리 대응 |
|---|---|---|---|
| 1 | 이미 있는 이름으로 파라미터 생성 | **수락**. 같은 이름 2개가 생기고 `Item()`은 하나만 잡음 | COM 호출 전에 존재 검사 → `ParameterAlreadyExistsError` |
| 2 | 빈 이름으로 생성 | 수락 후 `Length.3`으로 자동 명명 | `ParameterNameError` |
| 3 | 이름에 `\` 포함 | 수락. 정규화 이름과 구분 불가 | `ParameterNameError` |
| 4 | 스케치 이름 중복 | `rename`으로 같은 이름 2개 가능 | 열거해서 2개 이상이면 `AmbiguousNameError` |
| 5 | `Shapes.Remove` | **존재하지 않음** (`AttributeError`) | `Editor.Selection`으로 삭제 |
| 6 | Pad 삭제 | 스케치까지 연쇄 삭제 | 문서화 |
| 7 | **Pocket 삭제** | **스케치가 남는다** (Pad와 비대칭) | 문서화. 따로 지워야 함 |
| 8 | formula 제거 | **마지막 계산값이 그대로 남음** (되돌아가지 않음) | 문서화. 직접 복원해야 함 |
| 9 | `GetInertiaBoxElement` | **세션에 따라 조용히 전부 0을 반환한다.** 같은 모델·같은 호출에서 한 세션은 실제 값, 다른 세션은 0. 게다가 축 정렬이 아니라 주관성축 정렬이다 | 공개 API에서 제외. 부피·무게중심으로 판단 |
| 10 | `Selection.Search('Face,all')` | COM 오류. 올바른 쿼리는 `'Topology.Face,all'` | 검증된 쿼리 문자열만 쓴다 |
| 11 | 측정값 단위 | 전부 **SI(m, m3)**. 나머지 API는 mm | 경계에서 환산. 이름에 단위를 박아 혼동을 막는다 |
| 12 | `HybridBodies.Add()` | **새 기하 세트가 in-work object가 된다.** pad는 기하 세트에 들어갈 수 없어 이후 `AddNewPad`가 평면과 무관한 COM 오류로 거부된다 | `AppendHybridShape` 뒤마다 `InWorkObject = MainBody`로 되찾는다 |
| 13 | update 실패의 전파 | **한 번 실패한 feature를 지우기 전까지 이후 update가 전부 실패한다.** 무관한 연쇄 실패로 보인다 | `create_*` 뒤 update가 실패하면 반드시 그 feature를 지운다 |

추가로, 코드 쪽에서 잡힌 것들:

| 항목 | 내용 |
|---|---|
| 이름 형식이 생성 경로마다 다름 | `CreateDimension`으로 만들면 `3D Shape1\WIDTH`, UI f(x)로 만들면 `WIDTH`. `name`은 원본 유지, `short_name` 추가로 해결 |
| 수식 이름 ≠ 파라미터 이름 | 본문에는 `GetNameToUseInRelation()` 결과를 써야 한다. `.name`으로 조립하면 깨짐 |
| feature 내부 파라미터 폭증 | 패드 하나에 15개. `list()` 18개 중 사용자 것 3개. `user_parameters()`로 분리 |
| `math.isclose`의 기본 `rel_tol` | 생략하면 값이 클수록 허용 오차가 커져 갱신이 무시됨. `rel_tol=0.0` 명시 |
| `bool`은 `int`의 서브클래스 | `set(True)`가 조용히 1.0이 될 수 있어 명시적으로 거부 |
| 컬렉션은 1-based | `Item(0)`은 무효 |
| 클래스 본문의 `list` 섀도잉 | `def list()` 아래의 `-> list[str]` 애노테이션이 죽는다. `py_compile`로는 안 잡힘 |
| fake가 정규화 이름을 안 쓰면 중복 검사가 통째로 죽는다 | 존재 검사를 `Parameter.name == 요청이름`으로 했더니, `CreateDimension`이 `3D Shape1\Span`으로 저장하므로 **한 번도 일치하지 않았다.** 방금 만든 파라미터를 다시 만들어도 통과했다. unit 318개 전부 초록이었고 라이브 테스트만 잡았다. 기존 unit 테스트가 모두 fake에 정규화 안 된 이름을 미리 심어둔 탓이다. `short_name`까지 비교하도록 고치고, fake가 만드는 정규화 이름 그대로 검사하는 회귀 테스트를 `tests/unit/test_duplicate_name_detection.py`에 추가했다 |

---

## 4. 설계 결정과 이유

### 4.1 Save / PLMPropagate를 어떤 경로에서도 호출하지 않는다

저장은 사람이 UI에서 한다. 테스트로 고정돼 있어 `Part.Save`가 호출되면 실패한다.

이유: 3DEXPERIENCE의 저장은 파일 쓰기가 아니라 **서버 DB에 커밋**이다. 되돌릴 수 없고,
세션의 미저장 변경분을 전부 함께 커밋한다.

### 4.2 `set` / `create_*` / `ensure_*`는 `Part.Update()`를 자동 호출하지 않는다

여러 값을 바꾼 뒤 update를 한 번만 부를 수 있게 하기 위해서다.

### 4.3 검증되지 않은 COM API는 호출하지 않는다

probe로 실제 동작을 확인한 것만 라이브러리에 올린다. 2.2가 막혀 있는 이유가 이것이고,
"안 되는 걸 되는 척" 하지 않기 위한 비용이다.

### 4.4 이름 충돌은 조용히 넘어가지 않는다

CATIA는 중복 이름을 허용하지만 라이브러리는 거부한다. 존재 여부는 **열거로** 판정하고,
`Item(name)`이 던지는 예외를 "없음"의 근거로 쓰지 않는다 (COM 오류는 "없음"과 "일시적
실패"를 구분해 주지 않으므로 fail-open이 된다).

### 4.5 `pywintypes.com_error`는 라이브러리 밖으로 내보내지 않는다

모든 경계에서 `Auto3dxError` 계열로 변환하고 원인을 chain한다.

### 4.6 Formula는 플러그인이 아니라 단일 모듈이다

`~~.py`를 떨구면 API가 되는 동적 로딩 대신 `formulas/` 패키지로 구현했다. `parameters/`,
`geometry/`와 계층이 일관되고, 동적 로딩은 API 표면이 예측 불가해지며 테스트·정적 분석이
깨지는데 얻는 게 없다. 재사용 수식 묶음을 파일로 정의하는 건 이 위에 얹는 데이터 문제라
구조를 바꿀 필요가 없다.

---

## 5. 검증 방식

1. type library(`gen_py`)에서 정확한 signature를 확인한다. 추측하지 않는다.
2. `scripts/probes/`에 probe를 만들어 실행 중인 세션에서 실제로 호출한다.
3. 성공한 동작만 `docs/conventions.md`에 기록하고 라이브러리에 올린다.
4. 단위 테스트는 fake COM으로 CATIA 없이 돌린다
   (라이브러리가 `type(obj).__name__`으로 타입을 판별하므로 이름만 맞춘 평범한 클래스면 충분).
5. 통합 테스트는 실제 세션에서 돌리고 `finally`에서 원복한다. save는 호출하지 않는다.

**단위 테스트만으로는 부족하다는 게 실제로 증명됐다.** `Shapes.Remove`가 존재하지 않는다는
사실(3절 #5)은 단위 테스트가 전부 통과하는 상태에서 라이브 통합 테스트만이 잡아냈다.

외부 리뷰(Codex)도 두 차례 돌렸고, 지적의 전제를 매번 라이브로 검증한 뒤 반영 여부를
결정했다. 전제가 틀린 지적 2건은 근거를 기록하고 기각했다.

---

## 6. 다음 단계

측정·곡선 스케치·직사각형 패턴까지 public API, 단위 테스트, live integration을 통과했다.
Stiffener는 두 차례 시도에서 모두 update가 실패해 미검증으로 남긴다.

| 순서 | 항목 | 난이도 | 비고 |
|---|---|---|---|
| 1 | 모서리 fillet·chamfer, Shell·Thickness·Hole API | 완료 | 다섯 feature 모두 구현·live 검증. stale snapshot은 COM 전에 거부한다 |
| 2 | chamfer 인자 확정 | 완료 | `iMode=1`만 동작한다 (probe 35) |
| 3 | 사용자 정의 평면 API | 완료 | offset·각도 평면 모두 pad까지 검증됐다 (probe 36, conventions 1.2.7). `list`/`names`/`get`으로 모델에서 다시 찾고, 컬렉션이 기하 세트를 기억하지 않으므로 다른 프로세스가 만든 평면도 정리된다 (conventions 1.6, `test_plane_lookup.py`, live `test_user_planes_live.py`). 그 평면 위 스케치는 `sketch.support()`가 평면 자체를 돌려준다 (conventions 1.7, `test_sketch_support.py`) |
| 4 | `IsUpToDate` 의미 확인 | 완료 | `Part.is_up_to_date()` 구현 및 live false→true 전이 검증 (2.6) |
| 5 | 측정 기반 검증 | 완료 | `Part.measurement` 구현 및 live integration 완료 (2.6) |
| 6 | API design contract (`docs/api-design.md`) | 완료 | 앞으로의 공개 API 판단 기준 문서. 감사 결과를 바탕으로 결정했다 |
| 7 | Part당 공유 model generation | 완료 | 파라미터·스케치·평면·formula·제약·`update()`까지 mutation을 시도하는 모든 경로가 하나의 카운터를 공유한다. 같은 CATIA Part의 wrapper끼리도 COM 동일성으로 같은 카운터를 쓴다(`active_part()` 재호출, `part_named()`, 다른 `Catia` 인스턴스) (`api-design.md` 5.1절, `test_part_generation_wiring.py`, `test_shared_generation.py`, live `test_shared_generation_live.py`) |
| 8 | 예외 다섯 범주 재편 | 완료 | `SessionError`/`ValidationError`/`NotFoundError`/`ConflictError`/`AutomationError` (`api-design.md` 8절, `test_errors.py`) |
| 9 | 작은 패키지 루트 | 완료 | `Catia`/`Part`/예외 범주만 남기고 65개에서 축소 (`api-design.md` 13절, `test_public_exports.py`) |
| 10 | `only Part.update() rebuilds` 정책 테스트 | 완료 | 패키지 소스를 파싱해 `Update()`/`Save()`/`PLMPropagate()` 호출 위치를 고정 (`test_update_policy.py`) |
| 11 | `part.inspect` | 완료 | 이름·재빌드 상태·feature·스케치·사용자 파라미터에 더해 모든 body(main body는 COM 동일성으로 표시), Part 바로 아래 기하 세트와 그 요소, 모서리·면 개수, In-Work Object(`InWorkObjectInfo(name, kind, is_main_body)`, COM 객체 없음)까지 돌려준다. 중첩 기하 세트의 내용, body 안의 기하 세트, 기하 세트 안의 스케치는 live 근거가 없어 넣지 않았다 (`test_inspection.py`, live `test_inspection_live.py`) |
| 12 | topology 검색의 사용자 selection 복원 | 완료 | `part.topology.edges()`/`faces()`가 검색 전 selection을 캡처하고 뒤에 복원한 뒤 개수로 확인한다. CATIA가 복원 일부를 조용히 거부하면 스냅샷은 그대로 돌려주고 `SelectionNotRestoredWarning`을 낸다 (`test_topology_selection.py`, live `test_snapshots_restore_the_user_selection_and_stay_usable`) |
| 13 | 스레드 안전성 | 중간 | 미검증 (2.7) |
| 14 | Part 생성 재시도 | 외부 의존 | 라이선스 해결 필요 (2.1) |
| 15 | Multi-sections Solid (Loft) | 완료 (모서리 없는 섹션) | `create_multi_section_solid`/`get_`/`remove_`/`multi_section_solids`/`section_names()`. live: 원 두 개와 닫힌 spline NACA 2415/2412 날개가 공개 API만으로 만들어졌고, 새 프로세스에서 재발견·섹션 읽기·삭제·기준 복원까지 통과했다. 사각형과 선으로 닫은 에어포일처럼 모서리가 있는 섹션은 닫힘점 없이 update에 실패하며, `remove_multi_section_solid`로 복구된다. guide·spine·닫힘점·coupling은 미지원 (conventions 1.8, live `test_multi_section_solid_live.py`) |
| 16 | live 테스트 대상 Part 지정 | 완료 | `AUTO3DX_LIVE_PART`가 활성 Part와 일치해야 통합 테스트 세션이 시작된다. 이름을 지정하지 않은 Part에서 probe가 공유 기하 세트를 지운 사고에서 나온 규칙이다 (conventions 1.8) |
| 17 | Multi-Body | 완료 | `part.bodies`(`list`/`names`/`get`/`main`/`create`/`remove`), `part.work_in(body)`, `Body.features`/`sketch_names`/`is_visible`/`hide()`/`show()`. 스케치와 Part Design feature가 선택한 body에 만들어지고 조회되며, 블록을 어떻게 나가든 In-Work Object가 복원된다. live: 새 wrapper·새 프로세스 재발견(A→B acceptance), 숨김 read-back, 다섯 body enclosure에서 바깥 하우징만 숨김, 기준 복원. boolean 연산·이름 변경·body 안의 기하 세트는 미지원 (conventions 1.9, `test_multi_body.py`, live `test_multi_body_live.py`) |
| 18 | selection 기반 동작의 활성 Part 가드 | 완료 (임시 안전장치) | 비활성 Part의 `Selection.Search`가 활성 Part를 검색했다. topology 검색·`remove_*`·body 숨김/삭제가 활성 Part가 아니면 `InactivePartError`로 거부하고, 검사의 topology 개수는 `None`이다. 비활성 Part용 검증된 경로가 생기면 풀 수 있다 (conventions 1.9, api-design 7절) |
| 19 | body 단위 topology 범위와 소유권 | 완료 | body를 선택하고 `Topology.Edge,sel`로 검색하면 그 body만 나온다. `part.topology.edges(body=...)`/`faces(body=...)`, work_in 안에서는 자동. 모든 `Edge`/`Face`가 `Reference.Parent` 체인에서 읽은 소유 body를 들고 있고, 다른 body의 모서리로 feature를 만들면 COM 호출 전에 `CrossBodyReferenceError`. 소유 정보는 스냅샷마다 모델에서 다시 읽으므로 새 프로세스에서도 동작한다. CATIA가 소유를 알려주지 않으면 통과시킨다 (conventions 1.10) |
| 20 | non-main body 재빌드·측정 안전 | 완료 | `body.update()`/`part.update(body)`(`Part.UpdateObject`), `body.is_up_to_date`. 재빌드 안 된 대상 측정은 `TargetNotUpToDateError`로 거부하고, 측정이 재빌드하지는 않는다 (conventions 1.10) |
| 21 | EnumParam 읽기 | 완료 | `Value`가 없는 파라미터는 `ValueAsString()`으로 읽는다. 제약이 있는 Part에서 파라미터 열거가 깨지던 문제. 쓰기는 미검증이라 `set()`은 계속 거부 |
| 22 | 평면 support 사전 조건 | 완료 | 재빌드 안 된 평면 위 스케치는 `SupportNotUpdatedError`로 거부한다. 전에는 opaque E_FAIL이었다 |
| 23 | PartUpdateError 복구 정책 | 완료 (문서·안내) | 정상이던 값을 바꿔 실패한 경우는 값을 되돌리고 다시 update하는 것이 먼저다. 삭제는 애초에 만들어지지 않은 feature나 되돌릴 값이 없을 때만. live로 pad 30→1→30 복구 확인 (conventions 1.10) |
| 24 | 기존 feature 치수 편집 | 완료 | fillet `radius`, chamfer `length1`/`angle`, hole `diameter`/`depth`, shell 두 두께, thickness `offset`. 읽기·쓰기·update·형상 변화·새 wrapper·새 프로세스까지 확인한 것만 공개했다. setter는 재빌드하지 않고, 실패한 update는 값을 되돌려 복구한다 (conventions 1.11) |
| 25 | 스케치 요소 재발견 | 완료 | `sketch.get_element(name)`/`elements()`와 `SketchElement.name`/`radius`. CATIA 이름이 지속 identity이고, 새 프로세스에서 재발견한 선으로 새 제약을 만들고 update까지 성공했다. 선 좌표는 이 릴리스의 `Line2D`가 노출하지 않는다 (conventions 1.11) |
| 26 | feature 단위 작업 위치 | 완료 | `part.work_at(feature)`. 라이브에서 `PAD, FILLET` 트리의 `PAD`에서 작업하니 새 pad가 `PAD, NEW, FILLET`로 **바로 뒤에 삽입**됐다. 트리 재정렬이 아니다. 이전 In-Work Object는 정상·예외 모두 복원된다 (conventions 1.11) |
| 27 | 파라미터 의존성 보호 | 완료 (formula 한정) | `Formula.GetInParameter`로 각 formula의 입력을 읽어 `parameters.dependents(name)`을 만들고, 참조 중인 파라미터 삭제는 `ParameterInUseError`로 거부한다. 전에는 CATIA가 formula를 `deleted_*`로 고쳐 쓰고 Part가 not-up-to-date가 됐다. rule/check/law/program/design table은 미탐지 (conventions 1.11) |
| 28 | 원형 패턴 | 완료 (Z축) | `create_circular_pattern`과 `CircularPattern.angular_instances`/`angular_spacing_deg`. 디스크에서 6개 패턴이 구멍 5개 분량을 정확히 제거했고, 8개로 바꾸면 7개 분량이 됐다. 원점 XY 평면을 회전 중심·축으로 주면 Z축이다. YZ/ZX는 Z가 아니었지만 어느 축인지 확정 못 해 거부한다 (conventions 1.12) |
| 29 | body boolean 네 가지 | 완료 | remove/add/intersect/assemble 모두 부피로 검증. 대상은 work_in 중인 body, tool body는 소비되어 `part.bodies`에서 사라진다. `tool_body_name`은 feature에서 읽는다. **삭제하면 소비된 body까지 사라지고 되살릴 방법이 없어** `delete_consumed_body=True`를 요구한다 (conventions 1.12) |
| 30 | 스케치 제약 삭제 | 완료 | `sketch.constraints.remove()`. `Constraints.Remove`는 인덱스를 받고 제약끼리는 COM 동일성 비교가 안 돼서 이름으로 인덱스를 찾는다. edition 안에서 지우고, 이미 edit() 안이면 그 세션을 재사용한다 (conventions 1.12) |
| 31 | feature 억제 | 완료 | `is_active`/`activate()`/`deactivate()`. Activity는 feature 멤버가 아니라 `Part.Parameters`의 BoolParam이라 Parent 체인으로 Part를 찾아 읽는다. 억제는 generation을 올려 옛 스냅샷을 무효화한다. 상류 feature를 억제하면 update가 실패하고, 되돌리면 복구된다 (conventions 1.12) |
| 32 | 공개 세션 제목 | 완료 | `catia.active_window_title` 하나만 열어 acceptance 스크립트에서 raw COM을 없앴다. 창 조작은 하지 않는다 |
| 33 | 검사 분류 수정 | 완료 | `inspect.summary()`가 CircPattern과 boolean 네 종류를 `supported=True`로 보고한다. 처리하는 kind 목록과 `SUPPORTED_FEATURE_KINDS`가 어긋나지 않게 단위 테스트로 묶었다 |
| 34 | 면·모서리 측정 사실 | 완료 (평면·원통, 직선·원·호) | `MeasurableService`로 면적·중심·법선·반지름·길이·끝점을 읽는다. 면적만 m²라 변환한다. 분류는 typed getter의 응답으로 하고, 원뿔·구·스플라인은 unknown이다. 평면 법선 부호는 바깥 방향이 아니다 (conventions 1.13) |
| 35 | 의미 기반 topology 쿼리 | 완료 | `snapshot.query()`. 인덱스·descriptor 없이 윗면, 구멍 벽, 구멍 테두리, 수직 모서리를 골랐고, 새 프로세스에서 같은 쿼리로 다시 찾았다. `one()`은 0개·여러 개를 거부한다 |
| 36 | owner 의미 정정 | 완료 | `owner_feature_name`은 현재 소유 feature다. 필렛 뒤에는 모든 솔리드 모서리가 필렛을 가리킨다. `current_owner_feature_name` 별칭 추가. Parent 체인이 body에 닿지 않는 세션(재시작 뒤 AnyObject 체인)에서는 body 소속으로 찾는다 |
| 37 | Pad/Pocket 방향 | 완료 | `direction=` 인자와 `set_direction`/`reverse_direction`. CATIA 기본 pocket 방향은 스케치 법선 반대라 XY 아래 블록에서 **0 mm³를 자르고도 update가 성공**했다 |
| 38 | 평면 편집과 삭제 가드 | 완료 | `set_offset`/`set_angle` 후 update하면 스케치와 feature가 따라온다. 사용 중인 평면 삭제는 CATIA에서 성공하지만 다음 update가 실패하므로 `ReferenceInUseError`로 막고 `force=True`를 요구한다 |
| 39 | update 진단 | 부분 | `inspect.update_issues()`와 `PartUpdateError.issues`. `IsUpToDate`/`IsInactive`로 증상을 나열할 뿐 원인은 알려주지 않는다(boss 높이 오류에서 boss가 아니라 하류 fillet·pocket이 표시됨) |
| 40 | 사각형 구속 헬퍼 | 보류 | `rectangle()`은 선 4개에 제약 0개다. 다음 단계에서 다룬다 |

1번이 기능 개수로 압도적이다(약 80개). probe 17에서 막혔던 것이 probe 28에서 뚫렸고, 면은
probe 37에서 같은 경로로 뚫렸으므로, 남은 것은 "어느 모서리·어느 면인가"를 안정적으로
표현하는 설계다. probe 31에서 index와 BRep 문자열이 실제 재빌드에서 바뀌고
MeasurableService 길이 경로도 막힌 것이 확인됐다. 다음 후보는 검색 결과의 구체 wrapper가
노출하는 기하 속성 또는 다른 공식 측정 service다.

11번과 12번은 같은 live probe(`scripts/probes/38_inspection.py`)에 묶여 있다. 그 probe는
Part 이름·In-Work Object·Body의 Shape·Sketch·기하 세트의 HybridShape·사용자 파라미터·
`IsUpToDate`·모서리와 면 개수의 반복 일관성을 확인하고, 가장 중요하게는 topology 검색
전후로 selection을 캡처·복원해 PASS/FAIL로 보고하도록 만들어져 있다. 읽기 전용이며
아무것도 만들거나 지우지 않는다. 2026-09-15에 live로 실행했고 필요한 읽기와 비어 있지 않은
selection의 복원이 모두 통과했다(conventions 1.5). 그 증거로 11번과 12번을 모두 구현했다.
