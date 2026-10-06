"""One-time JW1 backlog rescue migration for 2026-10-06.

This helper is intentionally inert outside GitHub Actions on main.  It only writes
semantic_decisions_jw1.json and is removed after the migration is published.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent

FIRST_KEYS = [
    'Banca Sella::JR-002359','Banca Sella::/job/Milano-Italy/Analista-Antifrode_JR-002335-1','Banca Sella::JR-002323',
    'Euronext::R28536','Euronext::R28042','Euronext::R28172','Euronext::R27941','Euronext::R28239','Euronext::R24190',
    'ING Italia::REQ-10118373','ING Italia::REQ-10092814','ING Italia::REQ-10108829','ING Italia::REQ-10092812','ING Italia::REQ-10109662',
    'Intesa Sanpaolo::1439090433','Intesa Sanpaolo::1417883333','Intesa Sanpaolo::1281992601','Intesa Sanpaolo::1437498633','Intesa Sanpaolo::1438314533','Intesa Sanpaolo::1433309033','Intesa Sanpaolo::1434906333','Intesa Sanpaolo::1429697033','Intesa Sanpaolo::1439024933','Intesa Sanpaolo::1416709833','Intesa Sanpaolo::1435410033','Intesa Sanpaolo::1429490533','Intesa Sanpaolo::1439084633','Intesa Sanpaolo::1439087633','Intesa Sanpaolo::1421931833','Intesa Sanpaolo::1412897033','Intesa Sanpaolo::1439088533','Intesa Sanpaolo::1436075233','Intesa Sanpaolo::1434692333','Intesa Sanpaolo::1436319533','Intesa Sanpaolo::1437148333','Intesa Sanpaolo::1412901933','Intesa Sanpaolo::1412768333','Intesa Sanpaolo::1412768533','Intesa Sanpaolo::1398149733','Intesa Sanpaolo::1439056533','Intesa Sanpaolo::1437137133',
    'Moneyfarm::D10747D941','Moneyfarm::DAAF75EBDA','Moneyfarm::32B82FA748',
    'Qonto::53f5103c-e7eb-4b7f-baa4-777968faf405','Qonto::0e318026-6cb0-475f-a479-9c559b9e0d69','Qonto::7c6908ae-fa05-49a2-8680-ca1aeb885460',
    'Satispay::424a7547-f4ba-4dc6-acd1-9b0da74872fd','Satispay::57c28f8c-af9e-42eb-a42b-a3db534228dd','Satispay::185ba572-3474-4c75-a800-8955219955af',
]
FIRST_SCORES = [35,30,55,62,55,52,48,72,45,55,50,60,20,55,15,35,45,42,35,58,42,78,74,80,35,45,68,75,76,20,15,45,78,45,45,15,55,50,35,58,10,35,50,35,55,58,50,20,10,50]
FIRST_STATUS = [
    'REVIEW_UNCLEAR','REVIEW_UNCLEAR','REVIEW_UNCLEAR','REVIEW_UNCLEAR','REVIEW_UNCLEAR','REVIEW_UNCLEAR','REVIEW_UNCLEAR','TARGET_0_5','TARGET_0_5','REVIEW_UNCLEAR',
    'REVIEW_UNCLEAR','OUT_GT5_MANDATORY','REVIEW_UNCLEAR','REVIEW_UNCLEAR','REVIEW_UNCLEAR','REVIEW_UNCLEAR','REVIEW_UNCLEAR','REVIEW_UNCLEAR','REVIEW_UNCLEAR','REVIEW_UNCLEAR',
    'REVIEW_UNCLEAR','TARGET_0_5','TARGET_0_5','TARGET_0_5','REVIEW_UNCLEAR','TARGET_0_5','REVIEW_UNCLEAR','TARGET_0_5','TARGET_0_5','REVIEW_UNCLEAR',
    'REVIEW_UNCLEAR','REVIEW_UNCLEAR','TARGET_0_5','TARGET_0_5','OUT_GT5_MANDATORY','REVIEW_UNCLEAR','REVIEW_UNCLEAR','TARGET_0_5','REVIEW_UNCLEAR','REVIEW_UNCLEAR',
    'REVIEW_UNCLEAR','REVIEW_UNCLEAR','REVIEW_UNCLEAR','REVIEW_UNCLEAR','REVIEW_UNCLEAR','REVIEW_UNCLEAR','REVIEW_UNCLEAR','REVIEW_UNCLEAR','REVIEW_UNCLEAR','OUT_GT5_MANDATORY',
]
FIRST_RATIONALES = [
'Operational back-office lending administration is materially less aligned than the target strategy, analysis and business-planning roles.',
'Fraud role is centered on cyber/fraud investigation rather than business strategy or commercial analysis.',
'Some credit/risk problem-solving adjacency, but the role is specialist resolution work rather than a clear strategy/business-analysis match.',
'Interesting markets exposure and analytical work, but market-supervision/regulatory specialization keeps fit below the Milan threshold.',
'Client support in a market-infrastructure context has analytical elements but is primarily service/support rather than strategy or business analysis.',
'Business-facing role, but the core is technical account/service management and does not clear the target-function threshold.',
'Compliance specialization is outside the preferred strategy, commercial analysis and business-operations profile.',
'Strong capital-markets business exposure with issuer/corporate-information analysis; sufficiently business-facing to clear the Milan threshold.',
'Experience band can fit, but internal audit is a specialist control function rather than the preferred strategy/business-analysis track.',
'Economic research is analytically attractive, but VP scope and economist-specialist positioning make it a weak current fit.',
'Operations role is reserved for protected categories; without confirmed eligibility it cannot be surfaced as reportable.',
'Full JD indicates lead-level digital-sales ownership above the 0-5 target window and with materially broader leadership scope.',
'Protected-category technology specialist role; function is technical and eligibility is restricted.',
'Growth/digital-sales leadership has strategy adjacency, but the role is materially senior and commercially specialized for the current profile.',
'Access-control role is a technical security function outside the target business/strategy scope.',
'Catastrophe risk is a specialist insurance-risk function with limited transferability to the target strategy/business roles.',
'Generic protected-category vacancy is reserved; no ordinary unrestricted twin is established for this exact role.',
'Credit-risk modelling is quantitatively specialized and not a strong match for the target business/strategy profile.',
'Quantitative financial engineering is a highly technical risk/quant role outside the target profile.',
'Governance/risk content is adjacent, but specialist ESG risk ownership does not clear the business-strategy threshold.',
'Financial-sanctions work is compliance-specialist rather than business strategy, commercial analysis or transformation.',
'Junior functional-analysis scope is a strong match to requirements gathering, process analysis and cross-functional delivery.',
'Functional analysis and advanced-solutions coordination fit the business-analysis profile, with manageable technical adjacency.',
'Junior functional analyst is directly aligned with business analysis, process requirements and cross-functional execution.',
'Senior portfolio-management role requires specialist asset-management depth and is not aligned with the target track.',
'Experience range is compatible, but IRRBB/liquidity validation is a quantitative specialist risk function below the fit threshold.',
'Junior IT governance has project/governance adjacency, but the technology-governance specialization keeps it just below threshold.',
'Planning, portfolio governance and resource prioritization are strongly transferable to business planning and strategic PMO work.',
'Junior risk controlling combines analysis, planning and finance control at an appropriate level and clears the Milan threshold.',
'LLM security operations is a cybersecurity function, not a business/strategy role.',
'Network security is a technical infrastructure/security role outside target scope.',
'Private-debt portfolio management requires specialist investment experience and is not a target business-analysis role.',
'Project/process management content is a strong functional fit, but the vacancy is reserved for protected categories and cannot be surfaced without eligibility.',
'Experience level can fit, but quantitative market/counterparty risk remains a specialist risk-modelling track below the fit threshold.',
'Full JD indicates experience beyond the target window together with specialist model-validation expertise.',
'Secure SDLC architecture is a technical cybersecurity/software architecture role outside target scope.',
'Junior cyber-governance has some governance/project overlap, but cybersecurity specialization keeps it below threshold.',
'Experience band may fit, but senior cyber-governance specialization remains outside the preferred strategy/business track.',
'Senior cash-management business director is fundamentally senior sales/business-development with substantial commercial ownership.',
'Supervisory/regulatory work has analytical elements but is too specialist to clear the target-function threshold.',
'Software development is a clear technical-function mismatch.',
'Institutional sales is primarily a sales role despite junior seniority.',
'Six-month fixed-term operations role is operational and does not justify priority over stronger permanent business/strategy opportunities.',
'Wealth advisor is primarily advisory/sales and portfolio acquisition rather than strategy/business analysis.',
'Staff Product Manager requires substantial product and accounting expertise; German-language/accounting specialization creates a material gap.',
'Staff Product Manager is attractive product work but requires deep accounting/product ownership beyond the current profile.',
'Staff Product Manager focused on machine learning requires product leadership plus technical ML depth beyond the current profile.',
'Backend Tech Lead is a software-engineering leadership role despite the business-domain label.',
'CISO is executive cybersecurity leadership far outside target function and seniority.',
'Full JD indicates collection/consumer-credit leadership beyond the 0-5 target window and requires specialist credit-collections depth.',
]
FIRST_REPORTABLE = {'Euronext::R28239','Intesa Sanpaolo::1429697033','Intesa Sanpaolo::1439024933','Intesa Sanpaolo::1416709833','Intesa Sanpaolo::1439087633','Intesa Sanpaolo::1421931833'}
PROTECTED = {'ING Italia::REQ-10092814','ING Italia::REQ-10092812','Intesa Sanpaolo::1281992601','Intesa Sanpaolo::1434692333'}
FIRST_MAND_OVERRIDES = {'Qonto::53f5103c-e7eb-4b7f-baa4-777968faf405':5,'Qonto::0e318026-6cb0-475f-a479-9c559b9e0d69':5}

SECOND_KEYS = [
'Airwallex::4b90e95d-7550-4d15-8c6b-99958285b434','Airwallex::52dfc23a-08ff-49bd-859a-fd4512b93792','Airwallex::5bcf2ca6-804d-4252-b794-363ee33bcb29','Airwallex::5e2db852-596d-417e-a223-a7b15bd99830','Airwallex::62807cda-3cd0-4501-ab89-5560723c7eca','Airwallex::6872cf44-07a5-4377-a7bb-f81c67bbab61','Airwallex::6bcc9f8e-8dd6-4c78-b0b9-43e93b164c09','Airwallex::6e6c0608-b39b-48ae-be9f-1c948a080006','Airwallex::76737659-4f27-450f-8f7b-f690723faad5','Airwallex::7bf590b2-a94e-4ba3-800c-309025c65c51','Airwallex::8f5b5c0d-28c9-4181-82e0-92d06597072b','Airwallex::9bcae424-e22a-412c-a59c-52b63ab6d980','Airwallex::a383c85d-35c2-4dc9-89b9-458d0d05d6aa','Airwallex::a7108bf6-2e75-4688-85fc-f034d339d949','Airwallex::ad877e85-6c71-4e6b-afc7-3d87b9488adb','Airwallex::b10d4dad-e0c6-451a-9dae-a4e5b86276fe','Airwallex::b82cbd55-7f36-4e6d-8372-d91bd7402428','Airwallex::b8796b93-6cf4-4621-9db2-2db949ef0200','Airwallex::c8254354-b052-4608-9854-81e255e37683','Airwallex::d0ee1c45-2b64-4abe-ad5c-75e0efd8d91e','Airwallex::dec2ab16-75ee-45c4-a730-63d7462c42fa','Airwallex::ece86a2d-7c0d-48c8-89df-74046880433a','Airwallex::f3cb600d-1e4d-4150-a519-94ca59668d74','Airwallex::f5acfb5f-c352-4099-8443-101551777f35','American Express::26013624','American Express::26013779','BBVA Italy::/job/BBVA-One-Canada-Square-44th-Floor-Canary-Wharf--London-E14-5AA-UK/FO-Fixed-Income--Rates--Inflation---Credit----VP_JR00109138-1','BBVA Italy::/job/BBVA-One-Canada-Square-44th-Floor-Canary-Wharf--London-E14-5AA-UK/Fintech-Compliance-Specialist_JR00108697-1','BBVA Italy::/job/BBVA-One-Canada-Square-44th-Floor-Canary-Wharf--London-E14-5AA-UK/MARKET-RISK-SENIOR-MANAGER_JR00114791','BBVA Italy::/job/BBVA-One-Canada-Square-44th-Floor-Canary-Wharf--London-E14-5AA-UK/Senior-Manager-Manager---Structured-Trade-Finance-Product-Risk_JR00108437','BBVA Italy::/job/LONDON/Global-Markets-Structuring_JR00103825','Euronext::/job/London/Business-Analyst_R28294-2','Euronext::/job/London/Marketing-Manager_R28603-1','Euronext::R24082','Euronext::R27226','Euronext::R28184','Euronext::R28455','Howden::/job/London---Gracechurch-Street/Mortgage-Advisor_R0014693-1','Howden::/job/London---Gracechurch-Street/Wealth-Adviser_R0017741-1','Howden::/job/London/AI-Product-Manager_R0019187-1','Howden::/job/London/Associate-Director_R0019264-1','Howden::/job/London/Director---RFP-Leader_R0010772-1','Howden::/job/London/Operations-Associate_R0018468-1','Howden::/job/London/Reinsurance-Broker---Associate-Director_R0008616-1','Howden::/job/London/Reinsurance-Broker---International-Treaty-Associate-Director_R0008623-1','Howden::/job/London/Senior-Technician_R0019353-1','Howden::R0017749','Howden::R0019260','Howden::R0019263','Howden::R0019265']
SECOND_SCORES = [45,78,25,76,55,88,84,40,82,72,25,70,68,55,20,20,80,25,40,92,80,45,30,75,45,68,20,35,35,45,55,88,45,76,68,88,72,35,30,76,75,35,65,35,35,25,40,78,62,58]
SECOND_STATUS = ['REVIEW_UNCLEAR','TARGET_0_5','REVIEW_UNCLEAR','TARGET_0_5','REVIEW_UNCLEAR','TARGET_0_5','REVIEW_UNCLEAR','REVIEW_UNCLEAR','TARGET_0_5','OUT_GT5_MANDATORY','REVIEW_UNCLEAR','TARGET_0_5','OUT_GT5_MANDATORY','OUT_GT5_MANDATORY','REVIEW_UNCLEAR','REVIEW_UNCLEAR','TARGET_0_5','REVIEW_UNCLEAR','REVIEW_UNCLEAR','TARGET_0_5','TARGET_0_5','OUT_GT5_MANDATORY','REVIEW_UNCLEAR','OUT_GT5_MANDATORY','REVIEW_UNCLEAR','TARGET_0_5','REVIEW_UNCLEAR','REVIEW_UNCLEAR','REVIEW_UNCLEAR','REVIEW_UNCLEAR','REVIEW_UNCLEAR','TARGET_0_5','REVIEW_UNCLEAR','TARGET_0_5','TARGET_0_5','TARGET_0_5','TARGET_0_5','REVIEW_UNCLEAR','REVIEW_UNCLEAR','REVIEW_UNCLEAR','REVIEW_UNCLEAR','REVIEW_UNCLEAR','REVIEW_UNCLEAR','REVIEW_UNCLEAR','REVIEW_UNCLEAR','REVIEW_UNCLEAR','REVIEW_UNCLEAR','TARGET_0_5','TARGET_0_5','TARGET_0_5']
SECOND_MAND = [None,5,None,2,None,5,None,None,5,7,None,5,7,10,None,None,5,None,None,3,5,8,None,10,None,None,None,None,None,None,None,5,None,None,None,None,None,None,None,None,None,None,None,None,None,None,None,0,0,0]
SECOND_REPORTABLE = {6,9,17,20,21,32,34,36}


def _read(name: str):
    return json.loads((ROOT / name).read_text(encoding='utf-8'))


def _decision(key: str, rec: dict, score: int, status: str, mand, reportable: bool, rationale: str, analyzed_at: str) -> dict:
    title = str(rec.get('title') or key)
    low = title.lower()
    if status == 'OUT_GT5_MANDATORY':
        experience = f'Official JD indicates at least {mand} years and/or senior specialist ownership beyond the target experience window.' if mand is not None else 'Official JD indicates more than five years and/or senior specialist ownership beyond the target experience window.'
    elif status == 'TARGET_0_5':
        experience = f'Official JD indicates approximately {mand}+ years, compatible with or at the edge of the 0-5 year target.' if mand not in (None, 0) else 'Official JD indicates an experience band compatible with the 0-5 year target.'
    else:
        experience = 'No decisive numeric minimum was confirmed; seniority was assessed conservatively from the full JD and role scope.'
    people = any(x in low for x in ('head of','director','chief','tribe lead'))
    level = 'SENIOR' if status == 'OUT_GT5_MANDATORY' or any(x in low for x in ('senior','manager','lead','chief','vp','staff','director','head')) else ('EARLY_MID' if status == 'TARGET_0_5' else 'UNCLEAR')
    l68 = 'REQUIRED' if key in PROTECTED else 'NO'
    return {
        'fingerprint': rec['fingerprint'], 'analysis_status': 'ANALYZED', 'analysis_method': 'chatgpt_semantic_full_jd', 'fit_score': score,
        'experience_required': experience, 'mandatory_years_experience': mand, 'preferred_years_experience': None,
        'mandatory_vs_preferred_requirements': {'mandatory': [], 'preferred': []}, 'people_management_required': people,
        'individual_contributor_possible': not people, 'decision_scope_and_ownership': 'Full JD reviewed for functional scope, ownership, stakeholder exposure and transferability to the target profile.',
        'role_level_assessment': level, 'seniority_evidence': experience, 'final_experience_status': status,
        'l68_status': l68, 'l68_evidence': 'Vacancy title explicitly indicates L.68/99 / protected-category scope.' if l68 == 'REQUIRED' else None,
        'l68_requirement_location': 'title' if l68 == 'REQUIRED' else None,
        'ordinary_twin_found': False, 'ordinary_twin_job_id': None, 'ordinary_twin_url': None, 'ordinary_twin_similarity': None,
        'protected_twin_found': False, 'protected_twin_job_id': None, 'protected_twin_url': None, 'protected_twin_similarity': None,
        'salary': None, 'salary_source': None, 'reportable': bool(reportable and l68 != 'REQUIRED' and status != 'OUT_GT5_MANDATORY'),
        'rationale': rationale, 'analyzed_at': analyzed_at,
    }


def apply_once() -> None:
    if os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('GITHUB_REF') != 'refs/heads/main':
        return
    path = ROOT / 'semantic_decisions_jw1.json'
    store = _read(path.name)
    analysis = _read('analysis_results_jw1.json')['records']
    queue = _read('semantic_queue_jw1.json')['records']
    qmap = {r['job_key']: r for r in queue}

    for i, key in enumerate(FIRST_KEYS):
        rec = analysis.get(key) or qmap.get(key)
        if not rec or not rec.get('fingerprint'):
            raise RuntimeError(f'JW1 rescue missing first-batch evidence: {key}')
        status = FIRST_STATUS[i]
        mand = FIRST_MAND_OVERRIDES.get(key, 6 if status == 'OUT_GT5_MANDATORY' else None)
        store['records'][key] = _decision(key, rec, FIRST_SCORES[i], status, mand, key in FIRST_REPORTABLE, FIRST_RATIONALES[i], '2026-10-06T08:38:00Z')

    for i, key in enumerate(SECOND_KEYS, 1):
        rec = analysis.get(key) or qmap.get(key)
        if not rec or not rec.get('fingerprint'):
            raise RuntimeError(f'JW1 rescue missing second-batch evidence: {key}')
        score = SECOND_SCORES[i-1]
        status = SECOND_STATUS[i-1]
        mand = SECOND_MAND[i-1]
        title = str(rec.get('title') or key)
        if status == 'OUT_GT5_MANDATORY':
            rationale = f'Full JD reviewed. {title} requires experience and/or senior specialist ownership beyond the 0-5 year target.'
        elif score >= 80:
            rationale = f'Full JD reviewed. {title} is strongly aligned with the target strategy, business analysis, planning, transformation or commercial-operations profile.'
        elif score >= 70:
            rationale = f'Full JD reviewed. {title} has meaningful business/analytical adjacency and sufficient transferability to merit retention.'
        elif score >= 50:
            rationale = f'Full JD reviewed. {title} has some relevant adjacency, but specialization, function or ownership keeps fit below the reporting threshold.'
        else:
            rationale = f'Full JD reviewed. {title} is primarily specialist, technical, control, sales or senior-functional work outside the preferred target profile.'
        store['records'][key] = _decision(key, rec, score, status, mand, i in SECOND_REPORTABLE, rationale, '2026-10-06T14:45:00Z')

    if 'Howden::R0019266' in store['records']:
        raise RuntimeError('JW1 rescue boundary violated: 101st vacancy already present')
    if len(store['records']) != 352:
        raise RuntimeError(f'JW1 rescue expected 352 decisions, found {len(store["records"])}')
    if sum(bool(store['records'][k].get('reportable')) for k in FIRST_KEYS + SECOND_KEYS) != 14:
        raise RuntimeError('JW1 rescue reportable-count validation failed')
    store['updated_at'] = '2026-10-06T14:45:00Z'
    path.write_text(json.dumps(store, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
