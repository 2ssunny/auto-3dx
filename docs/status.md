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
- 실행 환경: `auto-3dx` conda env, Python 3.11.16 (64-bit), pywin32 312
- 테스트: **237 unit + 16 integration** (integration은 세션 상태에 따라 skip)
- probe: `scripts/probes/` 26개
- 브랜치: `develop` (push·PR 안 함)

---

## 1. 한 눈에

```text
[사람]  3DEXPERIENCE UI에서 Part 생성        <- 막힘. 2.1
   |
[auto-3dx]  attach  (이름으로 Part 선택 가능)
            파라미터 생성 / 수정 / 삭제
            스케치 생성 -> 점·선·원·사각형 (+ 회전축)
            패드 / 포켓 / Shaft / Groove / Mirror 생성 · 수정 · 삭제
            formula로 치수·각도 연동
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

### 2.2 Part Design 기능 대부분이 여전히 막혀 있다 (가장 큰 기능 공백)

```text
ShapeFactory.AddNew* : 90개
구현됨               : Pad, Pocket, Shaft, Groove, Mirror, Rib, Slot — 7개
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
AddNewRectPattern(...)     -> RectPattern 반환. Part.Update() 실패
```

**풀려면:** BRep 이름을 안정적으로 만들고 검증하는 설계가 필요하다. `Selection`으로 사용자가
찍은 면을 받는 경로는 자동화와 맞지 않고, BRep 문자열을 직접 만드는 경로는 모델이 바뀌면
깨진다. 이건 별도 과제다.

### 2.3 스케치 제약(Constraint)을 직접 걸 수 없다

사각형을 그리면 CATIA가 `Coincidence.1~4`를 자동 생성하지만, 라이브러리에서 제약을
지정하는 API는 없다. `Part.Constraints` / `Sketch.Constraints` 미조사.

**영향:** 완전 구속(fully constrained) 스케치를 코드로 만들 수 없다. 치수 제약을 formula로
구동하는 전형적인 파라메트릭 패턴이 아직 반쪽이다.

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

- 스케치 평면: 원점 3개(XY/YZ/ZX)만. 사용자 정의 평면 불가.
- 프로파일: 점·선·원·사각형만. 호·스플라인 불가.

### 2.6 update 성공 여부를 검증할 수 없다

`Part.Update()`가 예외 없이 끝난 것과 모델이 정상인 것은 별개다. `IsUpToDate`가 COM에
노출돼 있지만 인자 형식을 확인하지 않아 쓰지 않는다.

### 2.8 `AddNew*` 성공이 feature 유효를 뜻하지 않는다

```text
AddNewStiffener(sketch)  -> Stiffener 반환. 이후 Part.Update() 실패
AddNewRectPattern(...)   -> RectPattern 반환. 이후 Part.Update() 실패
```

객체는 트리에 생겼는데 모델이 재계산에 실패한다. **생성 호출의 성공은 검증이 아니다.**

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

| 순서 | 항목 | 난이도 | 비고 |
|---|---|---|---|
| 1 | 스케치 제약 | 중간 | 완전 구속 스케치 (2.3). 파라메트릭 워크플로의 핵심 |
| 2 | Length 외 파라미터 타입 / 단위 시스템 | 중간 | signature 확인됨 (2.5) |
| 3 | Rib / Slot | 중간 | 스케치 2개를 받는다 |
| 4 | Stiffener / Pattern 재조사 | 중간 | 생성은 되나 update 실패 (2.8). 인자를 다시 찾아야 함 |
| 5 | **BRep 참조 레이어** | **높음** | 열리면 fillet·chamfer·shell·hole 등이 풀린다 (2.2) |
| 6 | Part 생성 재시도 | 외부 의존 | 라이선스 해결 필요 (2.1) |

1번이 실질 가치가 가장 크다. 지금은 사각형을 그려도 CATIA가 자동 생성하는 구속에 의존하고
있어서, 치수를 파라미터로 확실히 잡아두는 파라메트릭 모델을 코드로 만들 수 없다.

5번은 기능 개수로는 가장 크지만(약 80개) 설계 부담도 가장 크고, probe 17에서 쉬운 우회로가
없다는 것이 확인됐다.
