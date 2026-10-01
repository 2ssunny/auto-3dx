# 새 Part 생성 (PLM object creation) — 탐색 결과

> **Contributor research note, written in Korean.** It records why auto-3dx 1.0.0 does not
> create PLM objects (Parts, Physical Products): the creation paths tried were blocked on the
> verified installation. Users create and open the Part in the 3DEXPERIENCE UI first. Export
> was investigated separately (`docs/api-design.md` section 12). The user guide is
> [`docs/v1.0.0.md`](v1.0.0.md).

Step 4의 사전 조사 기록이다. **아직 아무것도 구현하지 않았고, 생성도 저장도 실행하지 않았다.**
확인한 것은 "어떤 API를 통해야 하는가"까지다.

조사 환경: B428_Cloud, `auto-3dx` conda env (Python 3.11.16), pywin32 312.

---

## 1. V5식 파일 기반 경로는 쓸 수 없다

```text
Application.Documents        -> Documents (Count 2), 메서드 Add / NewFrom / Open / Read
Application.ActiveDocument   -> com_error "The method ActiveDocument failed"
```

`Documents` 객체 자체는 존재하고 `Add`도 노출돼 있지만, `ActiveDocument`가 실패한다.
V5의 `Documents.Add("Part")` 가정으로 접근하면 안 된다. 3DEXPERIENCE에서 Part는 파일이
아니라 PLM 객체 그래프이고, 진입점은 아래의 `Editor.GetService(...)` 계열이다.

## 2. 실제 진입점: `Editor.GetService(name)`

`Editor`가 노출하는 메서드는 `GetItem`과 `GetService` 둘뿐이다. 이 설치본에서 획득에
성공한 서비스:

| 서비스 | 획득 | 역할 |
|---|---|---|
| `PLMNewService` | O | **새 PLM 객체 생성** |
| `PLMOpenService` | O | 기존 PLM 엔티티 열기 |
| `PLMPropagateService` | O | **PLM 저장 / propagate** |
| `PLMProductService` | O | occurrence·representation 링크 구성 |
| `PLMRefreshService` | O | 세션 갱신 |
| `PLMScriptService` | O | — |
| `ProductSessionService` | O | — |
| `PLMDocumentServices` | O | 파일 첨부 document 생성 |
| `PLMSearchService`, `SystemService`, `VPMSessionService`, `DELPPRService` | X | 이 role/환경에서는 없음 |

## 3. type library에서 확인한 signature

```text
PLMNewService
    PLMCreate(iUserType, oEditor)
    SetAttributeValue(iAttributeID, iAttributeValue)
    getLastError(oErrorMessage, oErrorCode)

PLMOpenService
    PLMOpen(iPLMEntity, oEditor)
    PLMOpenInNewWindow(iPLMEntity, oEditor)

PLMPropagateService
    PLMPropagate()
    Save()

PLMProductService
    ComposeLink(iPLMOccurrence, iVPMRepInstance, iCATIAReference)
    props: EditedContent, RootOccurrence

PLMDocumentServices
    CreateDocument(iAttrNames, iAttrValues, iFilePathNames, iFileComment)

VPMInstances.Add(iProductReference, oProductInstance)
VPMRepInstances.Add(iRepInstanceName, iRepReference, oRepInstance)
```

`PLMOpenService`에는 생성 메서드가 없다. 생성은 `PLMNewService.PLMCreate` 하나뿐이다.

## 4. 예상 흐름

```text
editor.GetService("PLMNewService")
  -> SetAttributeValue(<속성 id>, <값>)      # 이름 등, PLMCreate 전에 지정
  -> PLMCreate(iUserType, oEditor)           # 새 객체 + 그 객체의 Editor
  -> oEditor.ActiveObject                    # 여기서 Part를 얻을 수 있는지 미확인
  -> (형상 생성 = Step 3, 이미 검증됨)
  -> PLMPropagateService.PLMPropagate()      # PLM 반영 -- 미실행
```

## 4.1 실행 결과 — 이 계정에서는 생성이 거부된다

`scripts/probes/15_plm_create.py`를 실제로 실행한 결과다.

```text
SetAttributeValue('V_Name', 'AUTO3DX_NEW_PRODUCT')  -> accepted
PLMCreate('VPMReference')                           -> 거부
```

거부 시 화면에 뜬 것:

```text
[Licensing]  Operation not authorized
```

Python 쪽에서 받은 것:

```text
com_error (-2147352567, 'Exception occurred.',
           (0, 'CATIAPLMNewService', 'The method PLMCreate failed', None, 0, -2147467259), None)
PLMNewService.getLastError() -> ('', 0)
```

읽어낼 수 있는 것:

- **user type 문자열과 속성 id는 맞다.** `SetAttributeValue('V_Name', ...)`가 통과했고,
  `PLMCreate`는 인자 오류가 아니라 권한에서 잘렸다.
- `getLastError`가 빈 메시지에 코드 0이다. **PLMNewService가 오류를 기록하지도 못했다**는
  뜻이고, 호출이 서비스 로직에 닿기 전에 더 아래 계층에서 차단됐다는 신호다.
- 다이얼로그 제목이 `Licensing`이다. role/권한 거부라면 보통 실질적인 메시지가 온다.

**PLM에는 아무것도 생성되지 않았고 저장도 시도하지 않았다.**

### 라이선스인지 role인지 구분하는 법

COM으로는 구분되지 않는다. `SystemConfiguration.GetProductNames(ioProductNames)`는
`(24588, 3)` in/out 배열이라 정확한 크기를 미리 알아야 하고, 크기를 모르면
`"The size of ..."` 오류가 난다. `IsProductAuthorized(name)`는 정확한 제품 코드를 알아야
의미가 있는데, 추측한 코드(`UVD`, `UVG`, `MD2`, `PLM`, `CATIA` 등)는 전부 `False`를
돌려주므로 신호로 쓸 수 없다.

대신 **CATIA UI에서 직접 새 Physical Product를 만들어 보면** 한 번에 갈린다.

```text
UI에서는 되고 COM만 안 됨   -> Automation 경로의 라이선스 문제. 재확보하면 풀릴 수 있다.
UI에서도 안 됨              -> 이 교육용 계정의 role에 생성 권한이 없다. 환경을 바꿔야 한다.
```

참고로 세션 시작 무렵 License Manager가 아래 둘을 확보하지 못했다고 보고했다.

```text
UVD - Engineering Expert for Education : Unable to connect to server
UVG - Program Manager for Education    : Unable to connect to server
```

이후 "License(s) have been successfully checked"로 복구됐지만, 생성에 필요한 라이선스가
저 둘 중 하나이고 아직 제대로 물리지 않았을 가능성이 남아 있다.

## 5. 확인된 것과 아직 모르는 것

확인됨:

1. **`iUserType` 문자열.** 세션에 열려 있는 객체의 `GetCustomType()`에서 그대로 나온다.

   ```text
   VPMRepReference.GetCustomType() -> '3DShape'        (3D Shape representation)
   VPMReference.GetCustomType()    -> 'VPMReference'   (Physical Product)
   ```

2. **이름 속성 id는 `V_Name`.** `GetAttributeValue`로 읽히고
   `PLMNewService.SetAttributeValue('V_Name', ...)`가 수락된다. 함께 읽히는 것:
   `PLM_ExternalID`, `V_description`, `policy`, `originated`, `modified`, `V_discipline`.

3. **PLM 객체 계층.**

   ```text
   VPMReference    (prd-R1132100891411-00394022)  Physical Product
     .Father 관계로 위로 올라감
   VPMRepReference (3sh-R1132100891411-00422533)  3D Shape
     -> Part (Automation 객체)
   ```

아직 모름 (생성이 거부되어 도달하지 못함):

4. `PLMCreate`가 돌려주는 Editor의 `ActiveObject`가 `Part`인지, `VPMRootOccurrence`를 거쳐
   3D Shape representation을 따로 만들어야 하는지.
5. Physical Product와 3D Shape를 각각 만들어야 하는지, `PLMCreate` 한 번으로 되는지.
6. `PLMPropagate()`의 실제 동작 범위. 세션의 미저장 변경분을 전부 커밋하는 것으로 보이지만
   실행해 본 적이 없다.

`getLastError`는 이 환경에서 `('', 0)`만 돌려주므로 진단에 쓸 수 없다.

## 6. 왜 여기서 멈췄는가

`PLMCreate`는 이름 그대로 PLM 객체를 만든다. 세션 안에만 존재하고 propagate 전까지는
저장되지 않을 가능성이 높지만, 그 사이에 PLM 쪽 식별자를 선점하는지 확인되지 않았다.
확인하려면 실제로 호출해야 하고, 그건 사용자의 실제 PLM 데이터베이스에 흔적을 남길 수 있다.

라이브러리 전체 규칙은 여전히 **어떤 경로에서도 Save / PLMPropagate를 호출하지 않는다**이며,
테스트로도 고정돼 있다. Step 4를 실제로 구현하려면 그 규칙을 의도적으로 여는 결정이
먼저 필요하다.

## 7. 재개할 때 할 일

1. 버려도 되는 PLM collaborative space에서 `PLMCreate`의 `iUserType` 후보를 하나씩 시도하고
   `getLastError`로 거부 사유를 읽는다.
2. 성공한 user type과 attribute id를 이 문서에 기록한다.
3. 생성된 Editor의 `ActiveObject` 타입을 확인한다.
4. 그 뒤에 `create_part()` 공개 API를 설계한다. save gate 정책
   (변경 성공 -> update 성공 -> validation 성공 -> 명시적 save)을 함께 정한다.
