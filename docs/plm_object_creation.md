# 새 Part 생성 (PLM object creation) — 탐색 결과

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

## 5. 아직 모르는 것 (실행해야만 알 수 있음)

1. **`iUserType`에 넣을 문자열.** `"VPMReference"` / `"Physical Product"` / `"3D Shape"` 중
   무엇인지, 또는 전혀 다른 형식인지 확인되지 않았다. 열거 가능한 API를 찾지 못했다.
2. **`SetAttributeValue`의 `iAttributeID`.** 이름을 지정하는 속성 id가 무엇인지 미확인.
3. `PLMCreate`가 돌려주는 Editor의 `ActiveObject`가 `Part`인지, 아니면
   `VPMRootOccurrence`를 거쳐 3D Shape representation을 따로 만들어야 하는지 미확인.
4. Physical Product와 3D Shape representation을 각각 만들어야 하는지, `PLMCreate` 한 번으로
   되는지 미확인.

`getLastError(oErrorMessage, oErrorCode)`가 있으니 실패 시 원인은 읽어낼 수 있다.

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
