"""Small user-feedback taxonomy. Never used as a hard-filter input."""
import os
import re

REJECTION_REASONS = {'TOO_SENIOR', 'SALARY_TOO_LOW', 'WRONG_FUNCTION', 'WRONG_LOCATION',
                     'FIXED_TERM', 'PURE_SALES', 'TOO_TECHNICAL', 'DOMAIN_GAP', 'OTHER'}
PATTERNS = {
    'TOO_SENIOR': r'too senior|troppo senior|troppa esperienza|seniority|too much experience',
    'SALARY_TOO_LOW': r'salary.*(?:low|below|€32k)|pay.*(?:low|below)|salar\w*.*bass|ral.*(?:bassa|sotto)|stipendio.*bass|compensation.*below',
    'WRONG_LOCATION': r'wrong location|wrong geography|fuori zona|localit[aà].*sbagliata|sede.*non|outside.*(?:geograph|location)',
    'FIXED_TERM': r'fixed.term|tempo determinato|temporary contract',
    'PURE_SALES': r'pure sales|troppo commerciale|vendita pura',
    'TOO_TECHNICAL': r'too technical|troppo tecnic',
    'DOMAIN_GAP': r'domain gap|domain.*(?:lack|missing)|manca.*esperienza.*settore',
    'WRONG_FUNCTION': r'outside the target job type|M&A in the job title|wrong function|funzione.*(?:sbagliata|non)|ruolo.*non.*target',
}


def infer_rejection_reason(reason):
    value = str(reason or '').strip()
    for category, pattern in PATTERNS.items():
        if re.search(pattern, value, re.I):
            return category
    return None


def reason_is_vague(reason):
    return bool(re.fullmatch(r'\s*(?:scarta|no|togli|non mi interessa|not interested|reject|discard)[.!\s]*', str(reason or ''), re.I)) or not str(reason or '').strip()


# One-time migration hook; inert outside GitHub Actions on main and removed after publication.
if os.environ.get('GITHUB_ACTIONS') == 'true' and os.environ.get('GITHUB_REF') == 'refs/heads/main':
    from jw1_rescue_once import apply_once as _apply_jw1_rescue_once
    _apply_jw1_rescue_once()
