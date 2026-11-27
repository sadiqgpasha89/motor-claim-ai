from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from packages.contracts.agents import AgentInvocationRequest, AgentInvocationResponse
from packages.contracts.errors import DomainError, ErrorCode
from packages.observability.logging import get_correlation_id
from packages.security.auth import UserContext
from services.claims.audit import emit_outbox_event, record_audit_event
from services.claims.models import (
    Approval,
    Claim,
    ClaimTask,
    Communication,
    Customer,
    EcosystemCoordination,
    Estimate,
    Evidence,
    ExtractedFact,
    Payment,
    Policy,
    Provider,
    Settlement,
    SLATimer,
    SurveyAssignment,
    Vehicle,
)
from services.claims.state_machine import ClaimStatus, to_canonical_state
from services.workflow.sla_engine import compute_timer_status

SUPPORTED_LANGUAGES: list[dict[str, str]] = [
    {"code": "en-IN", "label": "English", "native": "English"},
    {"code": "hi-IN", "label": "Hindi", "native": "हिन्दी"},
    {"code": "mr-IN", "label": "Marathi", "native": "मराठी"},
    {"code": "ta-IN", "label": "Tamil", "native": "தமிழ்"},
    {"code": "kn-IN", "label": "Kannada", "native": "ಕನ್ನಡ"},
]

SUPPORTED_CHANNELS: list[str] = ["whatsapp", "email", "sms", "portal"]

PROACTIVE_TRIGGER_CATALOG: list[dict[str, str]] = [
    {
        "trigger": "documents_missing",
        "label": "Documents are missing",
        "message_type": "document_reminder",
        "urgency": "high",
    },
    {
        "trigger": "photos_insufficient",
        "label": "Photos are insufficient",
        "message_type": "document_reminder",
        "urgency": "high",
    },
    {
        "trigger": "survey_scheduled",
        "label": "A survey is scheduled",
        "message_type": "status_update",
        "urgency": "medium",
    },
    {
        "trigger": "surveyor_delayed",
        "label": "The surveyor is delayed",
        "message_type": "delay_advisory",
        "urgency": "high",
    },
    {
        "trigger": "estimate_approved",
        "label": "The estimate is approved",
        "message_type": "status_update",
        "urgency": "medium",
    },
    {
        "trigger": "repair_begins",
        "label": "Repair work begins",
        "message_type": "status_update",
        "urgency": "medium",
    },
    {
        "trigger": "parts_delayed",
        "label": "Parts are delayed",
        "message_type": "delay_advisory",
        "urgency": "high",
    },
    {
        "trigger": "settlement_awaiting_approval",
        "label": "Settlement is awaiting approval",
        "message_type": "next_steps",
        "urgency": "medium",
    },
    {
        "trigger": "payment_processed",
        "label": "Payment has been processed",
        "message_type": "status_update",
        "urgency": "medium",
    },
    {
        "trigger": "claim_closed",
        "label": "The claim is closed",
        "message_type": "status_update",
        "urgency": "low",
    },
]

PROACTIVE_TRIGGER_MAP: dict[str, dict[str, str]] = {item["trigger"]: item for item in PROACTIVE_TRIGGER_CATALOG}

_LOCALIZED_STAGE_TITLES: dict[str, dict[str, str]] = {
    "en-IN": {
        "claim_registered": "Claim registered",
        "documents_verified": "Documents verified",
        "vehicle_inspection": "Vehicle inspection",
        "repair_approval": "Repair approval",
        "repair_and_settlement": "Repair and settlement",
    },
    "hi-IN": {
        "claim_registered": "दावा पंजीकृत",
        "documents_verified": "दस्तावेज़ सत्यापित",
        "vehicle_inspection": "वाहन निरीक्षण",
        "repair_approval": "मरम्मत स्वीकृति",
        "repair_and_settlement": "मरम्मत और निपटान",
    },
    "mr-IN": {
        "claim_registered": "दावा नोंदणीकृत",
        "documents_verified": "कागदपत्रे तपासली",
        "vehicle_inspection": "वाहन तपासणी",
        "repair_approval": "दुरुस्ती मंजुरी",
        "repair_and_settlement": "दुरुस्ती व निपटारा",
    },
    "ta-IN": {
        "claim_registered": "கோரிக்கை பதிவு செய்யப்பட்டது",
        "documents_verified": "ஆவணங்கள் சரிபார்க்கப்பட்டன",
        "vehicle_inspection": "வாகன ஆய்வு",
        "repair_approval": "பழுதுபார்ப்பு ஒப்புதல்",
        "repair_and_settlement": "பழுது மற்றும் தீர்வு",
    },
    "kn-IN": {
        "claim_registered": "ಕ್ಲೈಮ್ ನೋಂದಾಯಿಸಲಾಗಿದೆ",
        "documents_verified": "ದಾಖಲೆಗಳು ಪರಿಶೀಲಿಸಲ್ಪಟ್ಟಿವೆ",
        "vehicle_inspection": "ವಾಹನ ತಪಾಸಣೆ",
        "repair_approval": "ದುರಸ್ತಿ ಅನುಮೋದನೆ",
        "repair_and_settlement": "ದುರಸ್ತಿ ಮತ್ತು ಇತ್ಯರ್ಥ",
    },
}


def _fmt_short_date(dt: Optional[datetime]) -> str:
    if dt is None:
        return "Pending"
    return dt.strftime("%d %b").lstrip("0")


def _fmt_inr(val: Any) -> str:
    try:
        num = float(val or 0)
        return f"₹{num:,.2f}"
    except Exception:
        return f"₹{val}"


def _resolve_preferences(claim: Claim, customer: Optional[Customer]) -> dict[str, Any]:
    lang = (customer.preferred_language if customer and customer.preferred_language else None) or claim.preferred_language or "en-IN"
    if lang not in _LOCALIZED_STAGE_TITLES:
        lang = "en-IN"
    pref_channel = (customer.preferred_channel if customer and customer.preferred_channel else None) or claim.preferred_channel or "whatsapp"
    if pref_channel not in SUPPORTED_CHANNELS:
        pref_channel = "whatsapp"

    consent_wa = bool(customer.consent_whatsapp) if customer is not None else bool(claim.whatsapp_consent)
    if customer is not None and claim.whatsapp_consent is False:
        consent_wa = False
    consent_sms = bool(customer.consent_sms) if customer is not None else True
    consent_email = bool(customer.consent_email) if customer is not None else True
    proactive_enabled = bool(customer.proactive_updates_enabled) if customer is not None else True

    return {
        "preferred_language": lang,
        "preferred_channel": pref_channel,
        "consent_whatsapp": consent_wa,
        "consent_sms": consent_sms,
        "consent_email": consent_email,
        "proactive_updates_enabled": proactive_enabled,
        "whatsapp_consent_updated_at": (
            customer.whatsapp_consent_updated_at.isoformat()
            if customer and customer.whatsapp_consent_updated_at
            else None
        ),
        "phone_masked": customer.phone_masked if customer else "******4321",
        "email_masked": customer.email_masked if customer else "cu***@demo.in",
    }


def resolve_effective_channel(
    requested_channel: str,
    prefs: dict[str, Any],
) -> tuple[str, bool, str]:
    """Enforce WhatsApp consent guardrail and channel opt-in fallback."""
    ch = requested_channel if requested_channel in SUPPORTED_CHANNELS else prefs["preferred_channel"]
    if ch == "whatsapp" and not prefs["consent_whatsapp"]:
        fallback = "email" if prefs.get("consent_email", True) else "portal"
        return fallback, True, "WhatsApp consent is opted out; fell back to consented channel."
    if ch == "sms" and not prefs.get("consent_sms", True):
        fallback = "email" if prefs.get("consent_email", True) else "portal"
        return fallback, False, "SMS opt-in disabled; fell back to email/portal."
    return ch, False, "Preferred channel consent verified."


def compose_state_aware_message(
    trigger_event: str,
    language: str,
    ctx: dict[str, Any],
) -> dict[str, str]:
    """Synthesize state-aware, localized customer communications grounded in live claim state."""
    lang = language if language in _LOCALIZED_STAGE_TITLES else "en-IN"
    cn = str(ctx.get("claim_number", "CLAIM"))
    veh = str(ctx.get("vehicle_reg", "your vehicle"))
    status = str(ctx.get("claim_status", "IN_PROGRESS"))
    missing_docs_str = ", ".join(ctx.get("missing_documents") or []) or "Policy / RC / Driving Licence"
    photo_issues_str = ", ".join(ctx.get("photo_issue_details") or []) or "front/rear clear daylight photos"
    surveyor_name = str(ctx.get("surveyor_name") or "Assigned IIISLA Surveyor")
    appt_str = str(ctx.get("inspection_slot_label") or "shortly")
    delay_reason = str(ctx.get("delay_reason") or "high regional inspection volume")
    garage_name = str(ctx.get("garage_name") or "your selected network garage")
    est_amt = str(ctx.get("approved_estimate_label") or "assessed repair lines")
    repair_stage = str(ctx.get("repair_stage_label") or "body & mechanical work")
    delayed_parts = str(ctx.get("delayed_parts_label") or "OEM replacement parts")
    parts_eta = str(ctx.get("parts_eta_days") or "4-5")
    settlement_amt = str(ctx.get("settlement_net_label") or "assessed settlement")
    approval_gate = str(ctx.get("approval_gate_label") or "senior claims checker")
    payment_amt = str(ctx.get("payment_amount_label") or settlement_amt)
    payment_utr = str(ctx.get("payment_utr") or "UTR-CONFIRMED")
    next_step = str(ctx.get("next_expected_action") or "We will notify you on the next milestone.")

    if trigger_event == "documents_missing":
        msgs = {
            "en-IN": (
                f"Action needed: Pending documents for {cn}",
                f"Your motor claim {cn} ({veh}) is registered and moving forward, but we still need: {missing_docs_str}. Upload them directly in the Customer Portal or reply here on WhatsApp so verification can complete without delay.",
                "Upload missing documents",
            ),
            "hi-IN": (
                f"आवश्यक कार्रवाई: {cn} के लिए लंबित दस्तावेज़",
                f"आपका मोटर दावा {cn} ({veh}) पंजीकृत है और आगे बढ़ रहा है, लेकिन सत्यापन पूरा करने के लिए हमें अभी भी {missing_docs_str} की आवश्यकता है। कृपया इन्हें पोर्टल या WhatsApp पर अपलोड करें।",
                "दस्तावेज़ अपलोड करें",
            ),
            "mr-IN": (
                f"कृपया कागदपत्रे अपलोड करा: {cn}",
                f"तुमचा मोटर दावा {cn} ({veh}) नोंदवला आहे; पडताळणी पूर्ण करण्यासाठी कृपया {missing_docs_str} पोर्टल किंवा WhatsApp वर अपलोड करा.",
                "कागदपत्रे अपलोड करा",
            ),
            "ta-IN": (
                f"ஆவணங்கள் தேவை: {cn}",
                f"உங்கள் மோட்டார் கோரிக்கை {cn} ({veh}) பதிவு செய்யப்பட்டுள்ளது. சரிபார்ப்பை முடிக்க {missing_docs_str} ஆவணங்களை போர்ட்டல் அல்லது WhatsApp மூலம் பதிவேற்றவும்.",
                "ஆவணங்களை பதிவேற்றுக",
            ),
            "kn-IN": (
                f"ದಾಖಲೆಗಳು ಬಾಕಿ ಇವೆ: {cn}",
                f"ನಿಮ್ಮ ಮೋಟಾರ್ ಕ್ಲೈಮ್ {cn} ({veh}) ನೋಂದಾಯಿಸಲಾಗಿದೆ. ಪರಿಶೀಲನೆ ಪೂರ್ಣಗೊಳಿಸಲು ದಯವಿಟ್ಟು {missing_docs_str} ಅನ್ನು ಪೋರ್ಟಲ್ ಅಥವಾ WhatsApp ಮೂಲಕ ಅಪ್‌ಲೋಡ್ ಮಾಡಿ.",
                "ದಾಖಲೆಗಳನ್ನು ಅಪ್‌ಲೋಡ್ ಮಾಡಿ",
            ),
        }
        subj, body, cta = msgs[lang]
        return {"subject": subj, "body": body, "action_cta": cta, "message_type": "document_reminder"}

    if trigger_event == "photos_insufficient":
        msgs = {
            "en-IN": (
                f"Photo recapture requested for {cn}",
                f"While inspecting images on {cn} ({veh}), our Damage AI flagged insufficient clarity/angles ({photo_issues_str}). Please retake 2-3 clear daylight photos showing the full damaged panel so your repair approval isn't held up.",
                "Upload daylight photos",
            ),
            "hi-IN": (
                f"{cn} के लिए स्पष्ट फ़ोटो पुनः अपलोड करें",
                f"{cn} ({veh}) की छवियों की जांच में कुछ फ़ोटो धुंधली या अधूरी पाई गईं ({photo_issues_str})। कृपया दिन के उजाले में क्षतिग्रस्त हिस्से की स्पष्ट फ़ोटो अपलोड करें ताकि मरम्मत स्वीकृति तेज़ी से हो सके।",
                "स्पष्ट फ़ोटो अपलोड करें",
            ),
            "mr-IN": (
                f"{cn} साठी स्पष्ट फोटो पुन्हा अपलोड करा",
                f"{cn} ({veh}) मधील काही फोटो अंधुक किंवा अपूर्ण आहेत ({photo_issues_str}). दुरुस्ती मंजुरी जलद होण्यासाठी कृपया दिवसाच्या प्रकाशात स्पष्ट फोटो अपलोड करा.",
                "फोटो अपलोड करा",
            ),
            "ta-IN": (
                f"{cn} கோரிக்கைக்கு தெளிவான புகைப்படங்கள் தேவை",
                f"{cn} ({veh}) வாகனப் படங்களில் சில தெளிவற்றவை அல்லது கோணங்கள் குறைவு ({photo_issues_str}). பழுது ஒப்புதல் தாமதமாகாமல் இருக்க பகல் வெளிச்சத்தில் தெளிவான படங்களைப் பதிவேற்றவும்.",
                "புகைப்படங்களை பதிவேற்றுக",
            ),
            "kn-IN": (
                f"{cn} ಗಾಗಿ ಸ್ಪಷ್ಟ ಫೋಟೋಗಳನ್ನು ಮರು-ಅಪ್‌ಲೋಡ್ ಮಾಡಿ",
                f"{cn} ({veh}) ಚಿತ್ರಗಳಲ್ಲಿ ಕೆಲವು ಅಸ್ಪಷ್ಟವಾಗಿವೆ ({photo_issues_str}). ದುರಸ್ತಿ ಅನುಮೋದನೆ ವಿಳಂಬವಾಗದಂತೆ ಹಗಲಿನ ಬೆಳಕಿನಲ್ಲಿ ಸ್ಪಷ್ಟ ಫೋಟೋಗಳನ್ನು ಅಪ್‌ಲೋಡ್ ಮಾಡಿ.",
                "ಫೋಟೋ ಅಪ್‌ಲೋಡ್ ಮಾಡಿ",
            ),
        }
        subj, body, cta = msgs[lang]
        return {"subject": subj, "body": body, "action_cta": cta, "message_type": "document_reminder"}

    if trigger_event == "survey_scheduled":
        msgs = {
            "en-IN": (
                f"Vehicle inspection scheduled for {cn}",
                f"Good news on {cn} ({veh}): Licensed IIISLA surveyor {surveyor_name} is assigned and your inspection is scheduled for {appt_str} at {garage_name}. Need a different time slot? Let us know or request a callback.",
                "View inspection details",
            ),
            "hi-IN": (
                f"{cn} के लिए वाहन निरीक्षण निर्धारित",
                f"दावा {cn} ({veh}) पर अपडेट: लाइसेंस प्राप्त सर्वेयर {surveyor_name} नियुक्त किए गए हैं और आपका निरीक्षण {appt_str} को {garage_name} पर निर्धारित है। समय बदलने के लिए पोर्टल या WhatsApp से संपर्क करें।",
                "निरीक्षण विवरण देखें",
            ),
            "mr-IN": (
                f"{cn} साठी वाहन तपासणी नियोजित",
                f"दावा {cn} ({veh}) साठी सर्वेक्षक {surveyor_name} यांची नेमणूक झाली असून तपासणी {appt_str} रोजी {garage_name} येथे नियोजित आहे.",
                "तपशील पहा",
            ),
            "ta-IN": (
                f"{cn} வாகன ஆய்வு நேரம் உறுதி செய்யப்பட்டது",
                f"கோரிக்கை {cn} ({veh}): உரிமம் பெற்ற ஆய்வாளர் {surveyor_name} நியமிக்கப்பட்டு {appt_str} அன்று {garage_name}-இல் ஆய்வு திட்டமிடப்பட்டுள்ளது.",
                "ஆய்வு விவரம் காண்க",
            ),
            "kn-IN": (
                f"{cn} ವಾಹನ ತಪಾಸಣೆ ನಿಗದಿಯಾಗಿದೆ",
                f"ಕ್ಲೈಮ್ {cn} ({veh}): ಪರವಾನಗಿ ಪಡೆದ ಸರ್ವೇಯರ್ {surveyor_name} ನೇಮಕಗೊಂಡಿದ್ದು, ತಪಾಸಣೆ {appt_str} ರಂದು {garage_name} ನಲ್ಲಿ ನಿಗದಿಯಾಗಿದೆ.",
                "ತಪಾಸಣೆ ವಿವರ ನೋಡಿ",
            ),
        }
        subj, body, cta = msgs[lang]
        return {"subject": subj, "body": body, "action_cta": cta, "message_type": "status_update"}

    if trigger_event == "surveyor_delayed":
        msgs = {
            "en-IN": (
                f"Surveyor delay advisory & priority escalation: {cn}",
                f"We noticed a delay on {cn} ({veh}) from {surveyor_name} ({delay_reason}). We have already triggered an automated SLA follow-up and alerted a human claims specialist so your vehicle inspection is prioritized within 24 hours.",
                "Escalate to human specialist",
            ),
            "hi-IN": (
                f"सर्वेयर विलंब सूचना व प्राथमिकता एस्केलेशन: {cn}",
                f"दावा {cn} ({veh}) पर {surveyor_name} के निरीक्षण/रिपोर्ट में देरी ({delay_reason}) देखी गई है। हमने SLA फॉलो-अप और प्राथमिकता एस्केलेशन सक्रिय कर दिया है; 24 घंटे के भीतर अगला अपडेट मिलेगा।",
                "विशेषज्ञ से बात करें",
            ),
            "mr-IN": (
                f"सर्वेक्षक विलंब सूचना: {cn}",
                f"दावा {cn} ({veh}) वर {surveyor_name} यांच्याकडून विलंब ({delay_reason}) आढळला आहे. SLA फॉलो-अप सुरू केला असून २४ तासांत अद्यतन दिले जाईल.",
                "तज्ज्ञांशी संपर्क साधा",
            ),
            "ta-IN": (
                f"ஆய்வாளர் தாமத அறிவிப்பு: {cn}",
                f"கோரிக்கை {cn} ({veh}) ஆய்வாளர் {surveyor_name} தாமதம் ({delay_reason}) கண்டறியப்பட்டது. முன்னுரிமை SLA நடவடிக்கை எடுக்கப்பட்டுள்ளது; 24 மணி நேரத்தில் தகவல் வரும்.",
                "மனித உதவி கோரவும்",
            ),
            "kn-IN": (
                f"ಸರ್ವೇಯರ್ ವಿಳಂಬ ಮಾಹಿತಿ: {cn}",
                f"ಕ್ಲೈಮ್ {cn} ({veh}) ನಲ್ಲಿ {surveyor_name} ಅವರಿಂದ ವಿಳಂಬ ({delay_reason}) ಕಂಡುಬಂದಿದೆ. ಆದ್ಯತೆಯ SLA ಫಾಲೋ-ಅಪ್ ಸಕ್ರಿಯಗೊಳಿಸಲಾಗಿದೆ; 24 ಗಂಟೆಗಳಲ್ಲಿ ಮುಂದಿನ ಮಾಹಿತಿ ನೀಡಲಾಗುವುದು.",
                "ತಜ್ಞರ ಸಹಾಯ ಪಡೆಯಿರಿ",
            ),
        }
        subj, body, cta = msgs[lang]
        return {"subject": subj, "body": body, "action_cta": cta, "message_type": "delay_advisory"}

    if trigger_event == "estimate_approved":
        msgs = {
            "en-IN": (
                f"Repair estimate approved for {cn} ({est_amt})",
                f"Your repair estimate for {cn} ({veh}) at {garage_name} has been validated and approved for {est_amt}. Parts allocation and repair scheduling are moving forward now.",
                "Track repair progress",
            ),
            "hi-IN": (
                f"{cn} का मरम्मत अनुमान स्वीकृत ({est_amt})",
                f"{garage_name} पर आपके वाहन ({veh}) के दावा {cn} का मरम्मत अनुमान {est_amt} के लिए स्वीकृत हो गया है। अब पुर्ज़ों और मरम्मत कार्य की तैयारी शुरू हो रही है।",
                "मरम्मत प्रगति देखें",
            ),
            "mr-IN": (
                f"{cn} साठी दुरुस्ती अंदाज मंजूर ({est_amt})",
                f"{garage_name} येथील दावा {cn} ({veh}) चा दुरुस्ती अंदाज {est_amt} साठी मंजूर झाला आहे.",
                "दुरुस्ती स्थिती पहा",
            ),
            "ta-IN": (
                f"{cn} பழுது மதிப்பீடு ஒப்புதல் ({est_amt})",
                f"{garage_name}-இல் உங்கள் {cn} ({veh}) கோரிக்கையின் பழுது மதிப்பீடு {est_amt}-க்கு ஒப்புதல் அளிக்கப்பட்டது.",
                "பழுது நிலையைப் பார்க்கவும்",
            ),
            "kn-IN": (
                f"{cn} ದುರಸ್ತಿ ಅಂದಾಜು ಅನುಮೋದಿತವಾಗಿದೆ ({est_amt})",
                f"{garage_name} ನಲ್ಲಿ ನಿಮ್ಮ ಕ್ಲೈಮ್ {cn} ({veh}) ದುರಸ್ತಿ ಅಂದಾಜು {est_amt} ಗೆ ಅನುಮೋದನೆಗೊಂಡಿದೆ.",
                "ದುರಸ್ತಿ ಪ್ರಗತಿ ನೋಡಿ",
            ),
        }
        subj, body, cta = msgs[lang]
        return {"subject": subj, "body": body, "action_cta": cta, "message_type": "status_update"}

    if trigger_event == "repair_begins":
        msgs = {
            "en-IN": (
                f"Repair work has begun on {veh} ({cn})",
                f"Workshop update on {cn}: {garage_name} has started repairs on {veh} (current milestone: {repair_stage}). We will update you automatically as painting, QC checks, and delivery readiness progress.",
                "View repair tracker",
            ),
            "hi-IN": (
                f"{veh} की मरम्मत शुरू हो गई है ({cn})",
                f"वर्कशॉप अपडेट ({cn}): {garage_name} ने {veh} की मरम्मत शुरू कर दी है (वर्तमान चरण: {repair_stage})। QC और डिलीवरी तैयार होने पर हम आपको तुरंत सूचित करेंगे।",
                "मरम्मत ट्रैकर देखें",
            ),
            "mr-IN": (
                f"{veh} चे दुरुस्ती काम सुरू झाले ({cn})",
                f"{garage_name} येथे {cn} ({veh}) चे दुरुस्ती काम सुरू झाले आहे (टप्पा: {repair_stage}).",
                "ट्रॅकर पहा",
            ),
            "ta-IN": (
                f"{veh} பழுதுபார்க்கும் பணி தொடங்கியது ({cn})",
                f"{garage_name}-இல் {cn} ({veh}) பழுதுபார்க்கும் பணி தொடங்கியுள்ளது (நிலை: {repair_stage}).",
                "பழுது நிலையைப் பார்க்கவும்",
            ),
            "kn-IN": (
                f"{veh} ದುರಸ್ತಿ ಕಾರ್ಯ ಪ್ರಾರಂಭವಾಗಿದೆ ({cn})",
                f"{garage_name} ನಲ್ಲಿ {cn} ({veh}) ದುರಸ್ತಿ ಕಾರ್ಯ ಆರಂಭವಾಗಿದೆ (ಹಂತ: {repair_stage}).",
                "ಟ್ರ್ಯಾಕರ್ ನೋಡಿ",
            ),
        }
        subj, body, cta = msgs[lang]
        return {"subject": subj, "body": body, "action_cta": cta, "message_type": "status_update"}

    if trigger_event == "parts_delayed":
        msgs = {
            "en-IN": (
                f"Parts delay update for {cn} (ETA ~{parts_eta} days)",
                f"Heads-up on {cn} ({veh}): {garage_name} reported a supply wait for {delayed_parts} (estimated arrival in {parts_eta} days). Our ecosystem team is tracking the OEM order and you can request a specialist callback anytime.",
                "View parts ETA or escalate",
            ),
            "hi-IN": (
                f"{cn} के स्पेयर पार्ट्स में देरी (अनुमानित {parts_eta} दिन)",
                f"दावा {cn} ({veh}) पर सूचना: {garage_name} में {delayed_parts} की आपूर्ति में लगभग {parts_eta} दिनों की प्रतीक्षा है। हमारी टीम OEM ऑर्डर ट्रैक कर रही है।",
                "पार्ट्स ETA देखें",
            ),
            "mr-IN": (
                f"{cn} साठी सुटे भाग येण्यास विलंब (अंदाजे {parts_eta} दिवस)",
                f"दावा {cn} ({veh}): {garage_name} येथे {delayed_parts} साठी सुमारे {parts_eta} दिवसांची प्रतीक्षा आहे.",
                "तपशील पहा",
            ),
            "ta-IN": (
                f"{cn} உதிரி பாகங்கள் தாமதம் (சுமார் {parts_eta} நாட்கள்)",
                f"கோரிக்கை {cn} ({veh}): {garage_name}-இல் {delayed_parts} வர சுமார் {parts_eta} நாட்கள் ஆகும். எங்கள் குழு தொடர்ந்து கண்காணிக்கிறது.",
                "விவரம் காண்க",
            ),
            "kn-IN": (
                f"{cn} ಬಿಡಿಭಾಗಗಳ ವಿಳಂಬ ಮಾಹಿತಿ (ಅಂದಾಜು {parts_eta} ದಿನಗಳು)",
                f"ಕ್ಲೈಮ್ {cn} ({veh}): {garage_name} ನಲ್ಲಿ {delayed_parts} ಪೂರೈಕೆಗೆ ಸುಮಾರು {parts_eta} ದಿನಗಳು ಬೇಕಾಗಬಹುದು. ನಮ್ಮ ತಂಡ ಇದನ್ನು ಟ್ರ್ಯಾಕ್ ಮಾಡುತ್ತಿದೆ.",
                "ವಿವರ ನೋಡಿ",
            ),
        }
        subj, body, cta = msgs[lang]
        return {"subject": subj, "body": body, "action_cta": cta, "message_type": "delay_advisory"}

    if trigger_event == "settlement_awaiting_approval":
        msgs = {
            "en-IN": (
                f"Settlement of {settlement_amt} awaiting final approval ({cn})",
                f"Your itemized settlement of {settlement_amt} for {cn} ({veh}) is calculated and queued for independent Maker-Checker sign-off by our {approval_gate}. Once approved, Finance payout will be released immediately.",
                "View settlement breakdown",
            ),
            "hi-IN": (
                f"{cn} का {settlement_amt} निपटान अंतिम स्वीकृति के लिए प्रतीक्षारत",
                f"दावा {cn} ({veh}) के लिए {settlement_amt} की गणना पूरी हो चुकी है और {approval_gate} की स्वतंत्र स्वीकृति के लिए कतार में है। स्वीकृति मिलते ही भुगतान जारी कर दिया जाएगा।",
                "निपटान विवरण देखें",
            ),
            "mr-IN": (
                f"{cn} साठी {settlement_amt} निपटारा अंतिम मंजुरीच्या प्रतीक्षेत",
                f"दावा {cn} ({veh}) साठी {settlement_amt} रक्कम {approval_gate} यांच्या अंतिम मंजुरीच्या प्रतीक्षेत आहे.",
                "तपशील पहा",
            ),
            "ta-IN": (
                f"{cn} தீர்வுத் தொகை {settlement_amt} இறுதி ஒப்புதலுக்காகக் காத்திருக்கிறது",
                f"கோரிக்கை {cn} ({veh})-க்கு {settlement_amt} கணக்கிடப்பட்டு {approval_gate} ஒப்புதலுக்காக உள்ளது.",
                "தீர்வு விவரம் காண்க",
            ),
            "kn-IN": (
                f"{cn} ಇತ್ಯರ್ಥ ಮೊತ್ತ {settlement_amt} ಅಂತಿಮ ಅನುಮೋದನೆಗೆ ಬಾಕಿ ಇದೆ",
                f"ಕ್ಲೈಮ್ {cn} ({veh}) ಗಾಗಿ {settlement_amt} ಲೆಕ್ಕಾಚಾರ ಪೂರ್ಣಗೊಂಡಿದ್ದು {approval_gate} ಅನುಮೋದನೆಗೆ ಕಾಯುತ್ತಿದೆ.",
                "ಇತ್ಯರ್ಥ ವಿವರ ನೋಡಿ",
            ),
        }
        subj, body, cta = msgs[lang]
        return {"subject": subj, "body": body, "action_cta": cta, "message_type": "next_steps"}

    if trigger_event == "payment_processed":
        msgs = {
            "en-IN": (
                f"Payment processed for {cn}: {payment_amt} ({payment_utr})",
                f"Payment of {payment_amt} on {cn} ({veh}) has been processed and confirmed (Ref: {payment_utr}). Final quality check and vehicle handover are underway.",
                "Download payment summary",
            ),
            "hi-IN": (
                f"{cn} का भुगतान पूरा हुआ: {payment_amt} ({payment_utr})",
                f"दावा {cn} ({veh}) के लिए {payment_amt} का भुगतान सफलतापूर्वक प्रोसेस हो गया है (संदर्भ: {payment_utr})। अंतिम गुणवत्ता जांच और वाहन डिलीवरी प्रक्रिया चल रही है।",
                "भुगतान विवरण देखें",
            ),
            "mr-IN": (
                f"{cn} साठी पेमेंट पूर्ण: {payment_amt} ({payment_utr})",
                f"दावा {cn} ({veh}) साठी {payment_amt} चे पेमेंट यशस्वीरित्या पूर्ण झाले आहे (Ref: {payment_utr}).",
                "पावती पहा",
            ),
            "ta-IN": (
                f"{cn} பணம் செலுத்தப்பட்டது: {payment_amt} ({payment_utr})",
                f"கோரிக்கை {cn} ({veh})-க்கு {payment_amt} வெற்றிகரமாகச் செலுத்தப்பட்டது (Ref: {payment_utr}).",
                "பணம் விவரம் காண்க",
            ),
            "kn-IN": (
                f"{cn} ಪಾವತಿ ಪೂರ್ಣಗೊಂಡಿದೆ: {payment_amt} ({payment_utr})",
                f"ಕ್ಲೈಮ್ {cn} ({veh}) ಗೆ {payment_amt} ಪಾವತಿ ಯಶಸ್ವಿಯಾಗಿ ಪ್ರಕ್ರಿಯೆಗೊಂಡಿದೆ (Ref: {payment_utr}).",
                "ಪಾವತಿ ವಿವರ ನೋಡಿ",
            ),
        }
        subj, body, cta = msgs[lang]
        return {"subject": subj, "body": body, "action_cta": cta, "message_type": "status_update"}

    if trigger_event == "claim_closed":
        msgs = {
            "en-IN": (
                f"Claim {cn} is closed — Thank you",
                f"Your motor claim {cn} ({veh}) is now officially closed with all QA checks, repair confirmation, and settlement records archived. Need anything else or want to appeal? You can always reach a human specialist from your portal.",
                "View closed claim archive",
            ),
            "hi-IN": (
                f"दावा {cn} बंद कर दिया गया है — धन्यवाद",
                f"आपका मोटर दावा {cn} ({veh}) सभी QA जांच, मरम्मत पुष्टि और भुगतान मिलान के साथ सफलतापूर्वक बंद कर दिया गया है। किसी भी सहायता के लिए पोर्टल पर मानवीय सहायता उपलब्ध है।",
                "पूर्ण विवरण देखें",
            ),
            "mr-IN": (
                f"दावा {cn} बंद करण्यात आला आहे — धन्यवाद",
                f"तुमचा मोटर दावा {cn} ({veh}) सर्व तपासण्या आणि निपटान पूर्ण करून बंद करण्यात आला आहे.",
                "तपशील पहा",
            ),
            "ta-IN": (
                f"கோரிக்கை {cn} மூடப்பட்டது — நன்றி",
                f"உங்கள் மோட்டார் கோரிக்கை {cn} ({veh}) அனைத்து தரச் சோதனைகள் மற்றும் தீர்வுடன் வெற்றிகரமாக மூடப்பட்டது.",
                "விவரம் காண்க",
            ),
            "kn-IN": (
                f"ಕ್ಲೈಮ್ {cn} ಮುಚ್ಚಲಾಗಿದೆ — ಧನ್ಯವಾದಗಳು",
                f"ನಿಮ್ಮ ಮೋಟಾರ್ ಕ್ಲೈಮ್ {cn} ({veh}) ಎಲ್ಲಾ ಪರಿಶೀಲನೆ ಮತ್ತು ಇತ್ಯರ್ಥದೊಂದಿಗೆ ಯಶಸ್ವಿಯಾಗಿ ಮುಚ್ಚಲಾಗಿದೆ.",
                "ವಿವರ ನೋಡಿ",
            ),
        }
        subj, body, cta = msgs[lang]
        return {"subject": subj, "body": body, "action_cta": cta, "message_type": "status_update"}

    if trigger_event == "human_escalation_ack":
        esc_ref = str(ctx.get("escalation_ref") or "ESC-HUMAN")
        esc_reason = str(ctx.get("escalation_reason") or "customer request")
        msgs = {
            "en-IN": (
                f"Human specialist assigned for {cn} ({esc_ref})",
                f"We have escalated {cn} ({veh}) to a dedicated human claims specialist for '{esc_reason}'. Reference {esc_ref} is active with a 4-hour callback SLA in your preferred language ({lang}).",
                "Track escalation ticket",
            ),
            "hi-IN": (
                f"{cn} के लिए मानवीय दावा विशेषज्ञ नियुक्त ({esc_ref})",
                f"आपका अनुरोध '{esc_reason}' के लिए दावा {cn} ({veh}) को एक मानवीय विशेषज्ञ के पास भेज दिया गया है (संदर्भ: {esc_ref})। 4 घंटे के भीतर आपकी पसंदीदा भाषा में कॉल/संपर्क किया जाएगा।",
                "टिकट स्थिति देखें",
            ),
            "mr-IN": (
                f"{cn} साठी मानवी तज्ज्ञ नियुक्त ({esc_ref})",
                f"'{esc_reason}' साठी तुमचा दावा {cn} ({veh}) मानवी तज्ज्ञांकडे सोपवला आहे (संदर्भ: {esc_ref}). ४ तासांत संपर्क साधला जाईल.",
                "स्थिती पहा",
            ),
            "ta-IN": (
                f"{cn} கோரிக்கைக்கு மனித நிபுணர் நியமனம் ({esc_ref})",
                f"'{esc_reason}' காரணமாக {cn} ({veh}) மனித நிபுணரிடம் ஒப்படைக்கப்பட்டது (Ref: {esc_ref}). 4 மணி நேரத்திற்குள் தொடர்பு கொள்ளப்படும்.",
                "நிலையைக் காண்க",
            ),
            "kn-IN": (
                f"{cn} ಗಾಗಿ ಮಾನವ ತಜ್ಞರನ್ನು ನೇಮಿಸಲಾಗಿದೆ ({esc_ref})",
                f"'{esc_reason}' ಕುರಿತು ನಿಮ್ಮ ಕ್ಲೈಮ್ {cn} ({veh}) ಅನ್ನು ಮಾನವ ತಜ್ಞರಿಗೆ ವರ್ಗಾಯಿಸಲಾಗಿದೆ (Ref: {esc_ref}). 4 ಗಂಟೆಗಳಲ್ಲಿ ಸಂಪರ್ಕಿಸಲಾಗುವುದು.",
                "ಸ್ಥಿತಿ ನೋಡಿ",
            ),
        }
        subj, body, cta = msgs[lang]
        return {"subject": subj, "body": body, "action_cta": cta, "message_type": "next_steps"}

    # Fallback state-aware general status update
    msgs = {
        "en-IN": (
            f"Live update for {cn} ({status})",
            f"Your claim {cn} ({veh}) is currently in '{status}'. Next expected milestone: {next_step}.",
            "Open claim tracker",
        ),
        "hi-IN": (
            f"दावा {cn} की ताज़ा स्थिति ({status})",
            f"आपका दावा {cn} ({veh}) अभी '{status}' चरण में है। अगला चरण: {next_step}।",
            "दावा ट्रैकर खोलें",
        ),
        "mr-IN": (
            f"दावा {cn} स्थिती अद्यतन ({status})",
            f"तुमचा दावा {cn} ({veh}) सध्या '{status}' स्थितीत आहे. पुढील पाऊल: {next_step}.",
            "ट्रॅकर पहा",
        ),
        "ta-IN": (
            f"கோரிக்கை {cn} நேரலை நிலை ({status})",
            f"உங்கள் கோரிக்கை {cn} ({veh}) தற்போது '{status}' நிலையில் உள்ளது. அடுத்த படி: {next_step}.",
            "டிராக்கரைத் திறக்கவும்",
        ),
        "kn-IN": (
            f"ಕ್ಲೈಮ್ {cn} ಲೈವ್ ಸ್ಥಿತಿ ({status})",
            f"ನಿಮ್ಮ ಕ್ಲೈಮ್ {cn} ({veh}) ಪ್ರಸ್ತುತ '{status}' ಹಂತದಲ್ಲಿದೆ. ಮುಂದಿನ ಹಂತ: {next_step}.",
            "ಟ್ರ್ಯಾಕರ್ ತೆರೆಯಿರಿ",
        ),
    }
    subj, body, cta = msgs[lang]
    return {"subject": subj, "body": body, "action_cta": cta, "message_type": "status_update"}


def _gather_claim_cx_state(db: Session, claim: Claim) -> dict[str, Any]:
    customer = db.query(Customer).filter(Customer.id == claim.customer_id).first() if claim.customer_id else None
    policy = db.query(Policy).filter(Policy.id == claim.policy_id).first() if claim.policy_id else None
    vehicle = db.query(Vehicle).filter(Vehicle.id == claim.vehicle_id).first() if claim.vehicle_id else None
    evidences = db.query(Evidence).filter(Evidence.claim_id == claim.id).all()
    facts = db.query(ExtractedFact).filter(ExtractedFact.claim_id == claim.id).all()
    surveys = (
        db.query(SurveyAssignment)
        .filter(SurveyAssignment.claim_id == claim.id)
        .order_by(SurveyAssignment.assigned_at.desc())
        .all()
    )
    eco = db.query(EcosystemCoordination).filter(EcosystemCoordination.claim_id == claim.id).first()
    estimates = db.query(Estimate).filter(Estimate.claim_id == claim.id).order_by(Estimate.version.desc()).all()
    settlements = db.query(Settlement).filter(Settlement.claim_id == claim.id).order_by(Settlement.version.desc()).all()
    approvals = db.query(Approval).filter(Approval.claim_id == claim.id).order_by(Approval.created_at.desc()).all()
    payments = db.query(Payment).filter(Payment.claim_id == claim.id).order_by(Payment.created_at.desc()).all()
    timers = db.query(SLATimer).filter(SLATimer.claim_id == claim.id).all()
    comms = db.query(Communication).filter(Communication.claim_id == claim.id).order_by(Communication.created_at.desc()).all()
    tasks = db.query(ClaimTask).filter(ClaimTask.claim_id == claim.id).order_by(ClaimTask.created_at.desc()).all()

    surveyor = (
        db.query(Provider).filter(Provider.id == (eco.surveyor_id if eco and eco.surveyor_id else claim.assigned_surveyor_id)).first()
        if ((eco and eco.surveyor_id) or claim.assigned_surveyor_id)
        else None
    )
    garage = (
        db.query(Provider).filter(Provider.id == (eco.garage_id if eco and eco.garage_id else claim.assigned_garage_id)).first()
        if ((eco and eco.garage_id) or claim.assigned_garage_id)
        else None
    )
    return {
        "customer": customer,
        "policy": policy,
        "vehicle": vehicle,
        "evidences": evidences,
        "facts": facts,
        "surveys": surveys,
        "eco": eco,
        "estimates": estimates,
        "settlements": settlements,
        "approvals": approvals,
        "payments": payments,
        "timers": timers,
        "comms": comms,
        "tasks": tasks,
        "surveyor": surveyor,
        "garage": garage,
    }


def build_customer_claim_journey(db: Session, claim: Claim, *, language_override: Optional[str] = None) -> dict[str, Any]:
    """Build the 5-stage Motor Claim Tracker grounded in live claim state."""
    st = _gather_claim_cx_state(db, claim)
    prefs = _resolve_preferences(claim, st["customer"])
    lang = language_override if language_override in _LOCALIZED_STAGE_TITLES else prefs["preferred_language"]
    titles = _LOCALIZED_STAGE_TITLES[lang]

    evidences: list[Evidence] = st["evidences"]
    facts: list[ExtractedFact] = st["facts"]
    surveys: list[SurveyAssignment] = st["surveys"]
    eco: Optional[EcosystemCoordination] = st["eco"]
    estimates: list[Estimate] = st["estimates"]
    settlements: list[Settlement] = st["settlements"]
    approvals: list[Approval] = st["approvals"]
    payments: list[Payment] = st["payments"]
    timers: list[SLATimer] = st["timers"]
    surveyor: Optional[Provider] = st["surveyor"]
    garage: Optional[Provider] = st["garage"]
    vehicle: Optional[Vehicle] = st["vehicle"]

    canonical = to_canonical_state(claim.status)
    latest_survey = surveys[0] if surveys else None
    latest_est = estimates[0] if estimates else None
    latest_stl = settlements[0] if settlements else None
    latest_pmt = payments[0] if payments else None

    # Stage 1: Claim registered
    reg_date = _fmt_short_date(claim.created_at)
    peril_label = claim.peril_cause.replace("_", " ").capitalize()
    s1_status = "completed" if claim.status != ClaimStatus.SUBMITTED.value else "in_progress"
    s1_detail = f"{reg_date} · {peril_label} claim submitted"

    # Stage 2: Documents verified
    missing_docs = list(claim.missing_documents or [])
    poor_photos = [
        ev.filename
        for ev in evidences
        if ev.image_quality_status in {"blurry", "dark", "insufficient", "poor", "recapture_required"}
    ]
    recapture_files = list((claim.damage_report or {}).get("recapture_required_files", [])) if isinstance(claim.damage_report, dict) else []
    missing_angles = list((claim.damage_report or {}).get("missing_angles", [])) if isinstance(claim.damage_report, dict) else []
    photo_insufficient = bool(poor_photos or recapture_files or (len(missing_angles) >= 3))
    unresolved_mismatch = any(f.validation_status == "mismatch" for f in facts)
    has_policy_checked = claim.coverage_factsheet is not None
    has_doc_evidence = any(ev.doc_type in {"rc", "driving_licence", "policy", "pdf_claim_form"} for ev in evidences)

    if unresolved_mismatch:
        s2_status = "action_required"
        s2_detail = "Document mismatch needs clarification"
    elif missing_docs:
        s2_status = "action_required"
        s2_detail = f"Missing: {', '.join(missing_docs[:2])}" + ("..." if len(missing_docs) > 2 else "")
    elif photo_insufficient:
        s2_status = "action_required"
        s2_detail = "Photo recapture needed (clear daylight angles)"
    elif has_policy_checked and (has_doc_evidence or canonical not in {ClaimStatus.SUBMITTED.value, ClaimStatus.REGISTERED.value}):
        s2_status = "completed"
        s2_detail = "Policy and RC validated"
    elif has_policy_checked or evidences:
        s2_status = "in_progress"
        s2_detail = "Policy & document verification in progress"
    else:
        s2_status = "in_progress"
        s2_detail = "Policy check & document validation pending"

    # Stage 3: Vehicle inspection
    survey_timer_breached = any(
        t.stage in {"surveyor_allocation", "surveyor_report", "survey_report"}
        and compute_timer_status(t.due_at, t.completed_at, t.paused) == "breached"
        for t in timers
    )
    surveyor_delayed = bool(
        survey_timer_breached
        or (latest_survey and latest_survey.delay_reason)
        or (eco and eco.surveyor_followup_status in {"overdue", "escalated"})
    )
    if not claim.requires_mandatory_survey and (claim.risk_tier or "MEDIUM") == "LOW":
        s3_status = "completed"
        s3_detail = "Physical survey bypassed (Fast-Track < ₹50,000)"
    elif latest_survey and latest_survey.signed_by_surveyor:
        s3_status = "completed"
        s3_detail = f"Inspection completed · {surveyor.name.split('(')[0].strip() if surveyor else 'Surveyor report signed'}"
    elif surveyor_delayed:
        s3_status = "delayed"
        s3_detail = f"Surveyor delayed — priority follow-up active ({surveyor.name.split('(')[0].strip() if surveyor else 'SLA escalation'})"
    elif latest_survey and latest_survey.appointment_at:
        s3_status = "in_progress"
        slot_lbl = _fmt_short_date(latest_survey.appointment_at)
        s3_detail = f"Scheduled {slot_lbl} · {surveyor.name.split('(')[0].strip() if surveyor else 'Surveyor'}"
    elif eco and eco.inspection_scheduled_at:
        s3_status = "in_progress"
        slot_lbl = _fmt_short_date(eco.inspection_scheduled_at)
        s3_detail = f"Scheduled {slot_lbl} · {surveyor.name.split('(')[0].strip() if surveyor else 'Surveyor'}"
    elif claim.assigned_surveyor_id or (eco and eco.surveyor_id):
        s3_status = "in_progress"
        s3_detail = f"Surveyor assigned ({surveyor.name.split('(')[0].strip() if surveyor else 'scheduling slot'})"
    else:
        s3_status = "in_progress" if canonical in {
            ClaimStatus.TRIAGE.value,
            ClaimStatus.SURVEY_REQUIRED.value,
            ClaimStatus.INVESTIGATION_REQUIRED.value,
            ClaimStatus.VALIDATION.value,
        } else "pending"
        s3_detail = "Surveyor assignment in progress"

    # Stage 4: Repair approval
    est_approved = latest_est is not None and latest_est.status in {"approved", "validated", "accepted"}
    stl_approved = latest_stl is not None and latest_stl.approval_status == "approved"
    pending_app = any(a.decision == "pending" for a in approvals) or (
        latest_stl is not None and latest_stl.approval_status in {"pending_maker", "pending_checker"}
    )
    if stl_approved or est_approved or canonical in {
        ClaimStatus.APPROVED.value,
        ClaimStatus.PAYMENT_PENDING.value,
        ClaimStatus.PAYMENT_RECONCILIATION.value,
        ClaimStatus.CLOSED.value,
    }:
        s4_status = "completed"
        if latest_stl and stl_approved:
            s4_detail = f"Repair & settlement approved ({_fmt_inr(latest_stl.net_payable_inr)})"
        elif latest_est:
            s4_detail = f"Estimate approved ({_fmt_inr(latest_est.total_approved_inr)})"
        else:
            s4_detail = "Repair approval confirmed"
    elif pending_app or canonical == ClaimStatus.SETTLEMENT_PENDING_APPROVAL.value:
        s4_status = "in_progress"
        s4_detail = (
            f"Settlement ({_fmt_inr(latest_stl.net_payable_inr)}) awaiting Maker-Checker approval"
            if latest_stl
            else "Settlement awaiting approval"
        )
    elif latest_est is not None or canonical in {ClaimStatus.ASSESSMENT.value, ClaimStatus.ESTIMATE_VALIDATION.value}:
        s4_status = "in_progress"
        s4_detail = (
            f"Estimate ({_fmt_inr(latest_est.total_claimed_inr)}) under validation"
            if latest_est
            else "Damage assessment & estimate review in progress"
        )
    else:
        s4_status = "pending"
        s4_detail = "Pending assessment"

    # Stage 5: Repair and settlement
    parts_delayed = bool(eco and eco.parts_status in {"partial_backorder", "backordered"})
    repair_active = bool(
        (eco and eco.repair_status not in {"not_started", "", None})
        or claim.status == ClaimStatus.REPAIR_IN_PROGRESS.value
    )
    repair_done = bool(eco and eco.repair_completion_confirmed)
    pmt_confirmed = latest_pmt is not None and latest_pmt.status == "confirmed"
    pmt_pending_recon = latest_pmt is not None and latest_pmt.status == "timeout_reconcile_pending"

    if claim.status == ClaimStatus.CLOSED.value:
        s5_status = "completed"
        s5_detail = (
            f"Claim closed · {_fmt_inr(latest_pmt.amount_inr)} paid ({latest_pmt.gateway_reference})"
            if pmt_confirmed and latest_pmt
            else "Claim closed · Vehicle handed over"
        )
    elif pmt_confirmed and latest_pmt:
        s5_status = "in_progress" if not repair_done else "completed"
        s5_detail = f"Payment processed ({_fmt_inr(latest_pmt.amount_inr)} · {latest_pmt.gateway_reference})"
    elif pmt_pending_recon:
        s5_status = "in_progress"
        s5_detail = "Payment reconciliation in progress with bank gateway"
    elif parts_delayed and eco:
        s5_status = "delayed"
        delayed_items = [p.get("description", "part") for p in (eco.parts_availability or []) if p.get("availability") != "in_stock"]
        s5_detail = f"Parts delayed ({', '.join(delayed_items[:2]) or eco.parts_status})"
    elif repair_done:
        s5_status = "in_progress"
        s5_detail = f"Repair completed at {garage.name.split('(')[0].strip() if garage else 'garage'} · Payment finalizing"
    elif repair_active and eco:
        s5_status = "in_progress"
        s5_detail = f"Repair work in progress ({eco.repair_status.replace('_', ' ')})"
    elif stl_approved or canonical == ClaimStatus.APPROVED.value:
        s5_status = "in_progress"
        s5_detail = "Approved — awaiting repair kickoff & payment release"
    else:
        s5_status = "pending"
        s5_detail = "Not yet started"

    stages = [
        {
            "key": "claim_registered",
            "step": 1,
            "title": titles["claim_registered"],
            "status": s1_status,
            "detail": s1_detail,
            "date_label": reg_date,
        },
        {
            "key": "documents_verified",
            "step": 2,
            "title": titles["documents_verified"],
            "status": s2_status,
            "detail": s2_detail,
            "date_label": _fmt_short_date(evidences[0].created_at) if evidences else None,
        },
        {
            "key": "vehicle_inspection",
            "step": 3,
            "title": titles["vehicle_inspection"],
            "status": s3_status,
            "detail": s3_detail,
            "date_label": (
                _fmt_short_date(
                    (latest_survey.appointment_at if latest_survey else None)
                    or (eco.inspection_scheduled_at if eco else None)
                )
                if (latest_survey and latest_survey.appointment_at) or (eco and eco.inspection_scheduled_at)
                else None
            ),
        },
        {
            "key": "repair_approval",
            "step": 4,
            "title": titles["repair_approval"],
            "status": s4_status,
            "detail": s4_detail,
            "date_label": _fmt_short_date(latest_est.created_at) if latest_est else None,
        },
        {
            "key": "repair_and_settlement",
            "step": 5,
            "title": titles["repair_and_settlement"],
            "status": s5_status,
            "detail": s5_detail,
            "date_label": _fmt_short_date(latest_pmt.created_at) if latest_pmt else None,
        },
    ]

    completed_count = sum(1 for s in stages if s["status"] == "completed")
    in_prog_bonus = 0.5 if any(s["status"] in {"in_progress", "action_required", "delayed"} for s in stages) else 0.0
    progress_pct = min(100, int(round(((completed_count + in_prog_bonus) / 5.0) * 100)))
    current_stage = next(
        (s["key"] for s in stages if s["status"] in {"action_required", "delayed", "in_progress"}),
        stages[-1]["key"] if completed_count == 5 else stages[0]["key"],
    )

    return {
        "tracker_title": "Motor claim tracker",
        "claim_id": claim.id,
        "claim_number": claim.claim_number,
        "vehicle_reg": claim.vehicle_reg_input,
        "vehicle_label": f"{vehicle.make} {vehicle.model} ({vehicle.registration_number})" if vehicle else claim.vehicle_reg_input,
        "claim_status": claim.status,
        "canonical_state": canonical,
        "risk_tier": claim.risk_tier or "MEDIUM",
        "operational_path": claim.operational_path or "standard",
        "language": lang,
        "progress_pct": progress_pct,
        "current_stage_key": current_stage,
        "next_step_customer_friendly": claim.next_expected_action,
        "stages": stages,
    }


def inspect_claim_communication_context(
    db: Session,
    claim: Claim,
    *,
    trigger_override: Optional[str] = None,
    language_override: Optional[str] = None,
    channel_override: Optional[str] = None,
) -> dict[str, Any]:
    """Analyze live claim state across all 10 proactive triggers and synthesize state-aware messaging context."""
    st = _gather_claim_cx_state(db, claim)
    prefs = _resolve_preferences(claim, st["customer"])
    lang = language_override if language_override in _LOCALIZED_STAGE_TITLES else prefs["preferred_language"]
    requested_channel = channel_override if channel_override in SUPPORTED_CHANNELS else prefs["preferred_channel"]
    effective_channel, wa_blocked, channel_note = resolve_effective_channel(requested_channel, prefs)

    evidences: list[Evidence] = st["evidences"]
    surveys: list[SurveyAssignment] = st["surveys"]
    eco: Optional[EcosystemCoordination] = st["eco"]
    estimates: list[Estimate] = st["estimates"]
    settlements: list[Settlement] = st["settlements"]
    approvals: list[Approval] = st["approvals"]
    payments: list[Payment] = st["payments"]
    timers: list[SLATimer] = st["timers"]
    comms: list[Communication] = st["comms"]
    tasks: list[ClaimTask] = st["tasks"]
    surveyor: Optional[Provider] = st["surveyor"]
    garage: Optional[Provider] = st["garage"]

    latest_survey = surveys[0] if surveys else None
    latest_est = estimates[0] if estimates else None
    latest_stl = settlements[0] if settlements else None
    latest_pmt = payments[0] if payments else None

    # Build rich context values from actual claim state
    missing_docs = list(claim.missing_documents or [])
    poor_photos = [
        ev.filename
        for ev in evidences
        if ev.image_quality_status in {"blurry", "dark", "insufficient", "poor", "recapture_required"}
    ]
    dmg_report = claim.damage_report if isinstance(claim.damage_report, dict) else {}
    recapture_files = list(dmg_report.get("recapture_required_files", []))
    missing_angles = list(dmg_report.get("missing_angles", []))
    photo_issue_details = list(dict.fromkeys([*poor_photos, *recapture_files, *[f"missing {a} angle" for a in missing_angles[:2]]]))

    surveyor_name = surveyor.name.split("(")[0].strip() if surveyor else "Assigned IIISLA Surveyor"
    garage_name = garage.name.split("(")[0].strip() if garage else "Network Cashless Garage"

    appt_dt = (latest_survey.appointment_at if latest_survey else None) or (eco.inspection_scheduled_at if eco else None)
    inspection_slot_label = appt_dt.strftime("%d %b %Y, %H:%M UTC") if appt_dt else "upcoming inspection window"

    survey_timer_breached = any(
        t.stage in {"surveyor_allocation", "surveyor_report", "survey_report"}
        and compute_timer_status(t.due_at, t.completed_at, t.paused) == "breached"
        for t in timers
    )
    delay_reason = (
        (latest_survey.delay_reason if latest_survey and latest_survey.delay_reason else None)
        or ("SLA deadline exceeded; follow-up dispatched" if survey_timer_breached else "surveyor report pending")
    )

    delayed_parts_items = [
        p for p in ((eco.parts_availability if eco else None) or [])
        if p.get("availability") in {"backordered", "ordered_oem", "delayed"}
    ]
    delayed_parts_label = ", ".join(str(p.get("description") or p.get("part_code")) for p in delayed_parts_items[:2]) or "OEM body/electrical parts"
    parts_eta_days = max([int(p.get("eta_days", 5)) for p in delayed_parts_items], default=5)

    # Detect active triggers from live state
    detected: list[dict[str, Any]] = []

    if claim.status == ClaimStatus.CLOSED.value:
        detected.append({
            "trigger": "claim_closed",
            "label": PROACTIVE_TRIGGER_MAP["claim_closed"]["label"],
            "urgency": "low",
            "reason": "Claim has passed all QA controls and reached CLOSED state.",
        })
    if latest_pmt and latest_pmt.status == "confirmed":
        detected.append({
            "trigger": "payment_processed",
            "label": PROACTIVE_TRIGGER_MAP["payment_processed"]["label"],
            "urgency": "medium",
            "reason": f"Payment of {_fmt_inr(latest_pmt.amount_inr)} confirmed ({latest_pmt.gateway_reference}).",
        })
    if latest_stl and (
        latest_stl.approval_status in {"pending_maker", "pending_checker"}
        or any(a.decision == "pending" for a in approvals)
        or claim.status == ClaimStatus.SETTLEMENT_PENDING_APPROVAL.value
    ):
        detected.append({
            "trigger": "settlement_awaiting_approval",
            "label": PROACTIVE_TRIGGER_MAP["settlement_awaiting_approval"]["label"],
            "urgency": "medium",
            "reason": f"Settlement {_fmt_inr(latest_stl.net_payable_inr)} awaiting Maker-Checker DoA approval.",
        })
    if eco and eco.parts_status in {"partial_backorder", "backordered"}:
        detected.append({
            "trigger": "parts_delayed",
            "label": PROACTIVE_TRIGGER_MAP["parts_delayed"]["label"],
            "urgency": "high",
            "reason": f"Parts status='{eco.parts_status}' ({delayed_parts_label}, ETA ~{parts_eta_days}d).",
        })
    if (eco and eco.repair_status not in {"not_started", "", None}) or claim.status == ClaimStatus.REPAIR_IN_PROGRESS.value:
        detected.append({
            "trigger": "repair_begins",
            "label": PROACTIVE_TRIGGER_MAP["repair_begins"]["label"],
            "urgency": "medium",
            "reason": f"Workshop milestone '{eco.repair_status if eco else 'repair_in_progress'}' active at {garage_name}.",
        })
    if latest_est and latest_est.status in {"approved", "validated", "accepted"}:
        detected.append({
            "trigger": "estimate_approved",
            "label": PROACTIVE_TRIGGER_MAP["estimate_approved"]["label"],
            "urgency": "medium",
            "reason": f"Estimate v{latest_est.version} approved for {_fmt_inr(latest_est.total_approved_inr)}.",
        })
    if survey_timer_breached or (latest_survey and latest_survey.delay_reason) or (eco and eco.surveyor_followup_status in {"overdue", "escalated"}):
        detected.append({
            "trigger": "surveyor_delayed",
            "label": PROACTIVE_TRIGGER_MAP["surveyor_delayed"]["label"],
            "urgency": "high",
            "reason": f"Surveyor SLA/report delay detected ({delay_reason}).",
        })
    if (latest_survey and (latest_survey.appointment_at or latest_survey.status in {"assigned", "scheduled"})) or (
        eco and eco.inspection_status in {"scheduled", "rescheduled"}
    ):
        detected.append({
            "trigger": "survey_scheduled",
            "label": PROACTIVE_TRIGGER_MAP["survey_scheduled"]["label"],
            "urgency": "medium",
            "reason": f"Inspection scheduled with {surveyor_name} ({inspection_slot_label}).",
        })
    if photo_issue_details:
        detected.append({
            "trigger": "photos_insufficient",
            "label": PROACTIVE_TRIGGER_MAP["photos_insufficient"]["label"],
            "urgency": "high",
            "reason": f"Image quality/coverage issues: {', '.join(photo_issue_details[:3])}.",
        })
    if missing_docs:
        detected.append({
            "trigger": "documents_missing",
            "label": PROACTIVE_TRIGGER_MAP["documents_missing"]["label"],
            "urgency": "high",
            "reason": f"Missing required documents: {', '.join(missing_docs)}.",
        })

    # Choose primary trigger
    if trigger_override and (trigger_override in PROACTIVE_TRIGGER_MAP or trigger_override == "human_escalation_ack"):
        primary_trigger = trigger_override
    elif detected:
        # Prioritize urgent action/delay triggers first, otherwise latest lifecycle milestone
        high_triggers = [d["trigger"] for d in detected if d["urgency"] == "high"]
        primary_trigger = high_triggers[0] if high_triggers else detected[0]["trigger"]
    else:
        primary_trigger = "status_update"

    approval_gate_label = "Claims Manager (L2 DoA)" if (claim.risk_tier or "MEDIUM") == "HIGH" else "Claims Checker"
    repair_stage_label = (eco.repair_status.replace("_", " ") if eco and eco.repair_status else "repair initiated")

    ctx = {
        "claim_number": claim.claim_number,
        "vehicle_reg": claim.vehicle_reg_input,
        "claim_status": claim.status,
        "next_expected_action": claim.next_expected_action,
        "missing_documents": missing_docs,
        "photo_issue_details": photo_issue_details,
        "surveyor_name": surveyor_name,
        "inspection_slot_label": inspection_slot_label,
        "delay_reason": delay_reason,
        "garage_name": garage_name,
        "approved_estimate_label": _fmt_inr(latest_est.total_approved_inr) if latest_est else _fmt_inr(claim.estimated_loss_inr),
        "repair_stage_label": repair_stage_label,
        "delayed_parts_label": delayed_parts_label,
        "parts_eta_days": parts_eta_days,
        "settlement_net_label": _fmt_inr(latest_stl.net_payable_inr) if latest_stl else _fmt_inr(claim.estimated_loss_inr),
        "approval_gate_label": approval_gate_label,
        "payment_amount_label": _fmt_inr(latest_pmt.amount_inr) if latest_pmt else (_fmt_inr(latest_stl.net_payable_inr) if latest_stl else "INR 0.00"),
        "payment_utr": (latest_pmt.gateway_reference if latest_pmt and latest_pmt.gateway_reference else "UTR-CONFIRMED"),
    }

    composed = compose_state_aware_message(primary_trigger, lang, ctx)
    sent_triggers = {c.trigger_event for c in comms if c.trigger_event and c.trigger_event != "manual_update"}
    escalation_tasks = [t for t in tasks if t.task_type == "customer_human_escalation"]

    trigger_matrix = [
        {
            **item,
            "active_in_state": any(d["trigger"] == item["trigger"] for d in detected),
            "already_communicated": item["trigger"] in sent_triggers,
            "active_reason": next((d["reason"] for d in detected if d["trigger"] == item["trigger"]), None),
        }
        for item in PROACTIVE_TRIGGER_CATALOG
    ]

    return {
        "claim_id": claim.id,
        "claim_number": claim.claim_number,
        "claim_status": claim.status,
        "canonical_state": to_canonical_state(claim.status),
        "primary_trigger": primary_trigger,
        "detected_triggers": detected,
        "trigger_matrix": trigger_matrix,
        "state_context": ctx,
        "preferences": prefs,
        "requested_channel": requested_channel,
        "effective_channel": effective_channel,
        "whatsapp_blocked_no_consent": wa_blocked,
        "channel_resolution_note": channel_note,
        "recommended_message": {
            "trigger_event": primary_trigger,
            "language": lang,
            "channel": effective_channel,
            **composed,
        },
        "human_escalations": [
            {
                "task_id": t.id,
                "title": t.title,
                "description": t.description,
                "assigned_role": t.assigned_role,
                "status": t.status,
                "priority": t.priority,
                "due_at": t.due_at.isoformat() if t.due_at else None,
                "created_at": t.created_at.isoformat(),
                "metadata": t.metadata_json or {},
            }
            for t in escalation_tasks
        ],
    }


def dispatch_proactive_customer_update(
    db: Session,
    claim: Claim,
    *,
    actor: UserContext,
    trigger_event: Optional[str] = None,
    language: Optional[str] = None,
    channel: Optional[str] = None,
    force: bool = False,
) -> dict[str, Any]:
    """Invoke CustomerCommunicationAgent with live state context and persist proactive update."""
    from agents.specialists import AGENT_REGISTRY
    from services.agent_runtime.actions import ControlledActionExecutor
    from services.workflow.orchestrator import record_agent_publication

    cx = inspect_claim_communication_context(
        db,
        claim,
        trigger_override=trigger_event,
        language_override=language,
        channel_override=channel,
    )
    resolved_trigger = cx["primary_trigger"]
    msg = cx["recommended_message"]
    prefs = cx["preferences"]

    if not force:
        existing_same = (
            db.query(Communication)
            .filter(
                Communication.claim_id == claim.id,
                Communication.trigger_event == resolved_trigger,
                Communication.claim_state_snapshot == claim.status,
                Communication.language == msg["language"],
            )
            .first()
        )
        if existing_same:
            return {
                "dispatched": False,
                "deduplicated": True,
                "trigger_event": resolved_trigger,
                "communication_id": existing_same.id,
                "channel": existing_same.channel,
                "language": existing_same.language,
                "delivery_status": existing_same.delivery_status,
                "message": existing_same.body,
                "context": cx,
            }

    agent = AGENT_REGISTRY["customer_communication"]
    req = AgentInvocationRequest(
        tenant_id=claim.tenant_id,
        claim_id=claim.id,
        correlation_id=get_correlation_id(),
        workflow_run_id=(claim.workflow_state or {}).get("workflow_run_id", claim.id),
        actor_user_id=actor.user_id,
        actor_role=actor.role.value,
        product_code="PRIVATE_CAR_PACKAGE",
        claim_type=claim.claim_type,
        locale=msg["language"],
        rule_versions={"irdai": "IN-IRDAI-MC-2024:1.0.0"},
        minimised_facts={
            **cx["state_context"],
            "language": msg["language"],
            "channel": cx["requested_channel"],
            "consent_whatsapp": prefs["consent_whatsapp"],
            "consent_sms": prefs["consent_sms"],
            "consent_email": prefs["consent_email"],
            "phone_masked": prefs["phone_masked"],
            "trigger_event": resolved_trigger,
            "message_type": msg["message_type"],
            "subject": msg["subject"],
            "draft_message": msg["body"],
            "detected_triggers": [d["trigger"] for d in cx["detected_triggers"]],
            "is_adverse": claim.status == ClaimStatus.DECLINED_PARTIAL.value,
        },
        allowed_tools=sorted(agent.allowed_tools),
    )
    executor = ControlledActionExecutor(db=db, claim=claim, user=actor)
    resp: AgentInvocationResponse = agent.execute(req, action_executor=executor)
    record_agent_publication(db, claim=claim, agent_name="customer_communication", response=resp)

    comm_id = None
    delivery_status = "sent_mock"
    wa_msg_id = None
    final_channel = cx["effective_channel"]
    if resp.actions_executed:
        act = resp.actions_executed[0]
        comm_id = act.target_id
        delivery_status = str((act.payload or {}).get("delivery_status", delivery_status))
        wa_msg_id = (act.payload or {}).get("whatsapp_message_id")
        final_channel = str((act.payload or {}).get("channel", final_channel))

    record_audit_event(
        db,
        tenant_id=claim.tenant_id,
        claim_id=claim.id,
        actor_id=actor.user_id,
        actor_role=actor.role.value,
        action="PROACTIVE_CUSTOMER_COMM_DISPATCHED",
        object_type="communication",
        object_id=comm_id or claim.id,
        details={
            "trigger_event": resolved_trigger,
            "language": msg["language"],
            "requested_channel": cx["requested_channel"],
            "effective_channel": final_channel,
            "whatsapp_blocked_no_consent": cx["whatsapp_blocked_no_consent"],
            "whatsapp_message_id": wa_msg_id,
            "delivery_status": delivery_status,
        },
    )
    db.flush()
    return {
        "dispatched": True,
        "deduplicated": False,
        "trigger_event": resolved_trigger,
        "communication_id": comm_id,
        "channel": final_channel,
        "requested_channel": cx["requested_channel"],
        "whatsapp_blocked_no_consent": cx["whatsapp_blocked_no_consent"],
        "whatsapp_message_id": wa_msg_id,
        "language": msg["language"],
        "delivery_status": delivery_status,
        "subject": msg["subject"],
        "message": msg["body"],
        "agent_response": resp.model_dump(),
    }


def update_customer_communication_preferences(
    db: Session,
    claim: Claim,
    *,
    actor: UserContext,
    preferred_language: Optional[str] = None,
    preferred_channel: Optional[str] = None,
    consent_whatsapp: Optional[bool] = None,
    consent_sms: Optional[bool] = None,
    consent_email: Optional[bool] = None,
    proactive_updates_enabled: Optional[bool] = None,
) -> dict[str, Any]:
    customer = db.query(Customer).filter(Customer.id == claim.customer_id).first() if claim.customer_id else None
    now = datetime.now(timezone.utc)

    if preferred_language is not None:
        if preferred_language not in _LOCALIZED_STAGE_TITLES:
            raise DomainError(ErrorCode.VALIDATION_ERROR, f"Unsupported language '{preferred_language}'", status_code=400)
        claim.preferred_language = preferred_language
        if customer:
            customer.preferred_language = preferred_language

    if preferred_channel is not None:
        if preferred_channel not in SUPPORTED_CHANNELS:
            raise DomainError(ErrorCode.VALIDATION_ERROR, f"Unsupported channel '{preferred_channel}'", status_code=400)
        claim.preferred_channel = preferred_channel
        if customer:
            customer.preferred_channel = preferred_channel

    if consent_whatsapp is not None:
        claim.whatsapp_consent = bool(consent_whatsapp)
        if customer:
            customer.consent_whatsapp = bool(consent_whatsapp)
            customer.whatsapp_consent_updated_at = now

    if customer:
        if consent_sms is not None:
            customer.consent_sms = bool(consent_sms)
        if consent_email is not None:
            customer.consent_email = bool(consent_email)
        if proactive_updates_enabled is not None:
            customer.proactive_updates_enabled = bool(proactive_updates_enabled)

    prefs = _resolve_preferences(claim, customer)
    record_audit_event(
        db,
        tenant_id=claim.tenant_id,
        claim_id=claim.id,
        actor_id=actor.user_id,
        actor_role=actor.role.value,
        action="CUSTOMER_COMM_PREFERENCES_UPDATED",
        object_type="claim",
        object_id=claim.id,
        details=prefs,
    )
    emit_outbox_event(
        db,
        tenant_id=claim.tenant_id,
        aggregate_id=claim.id,
        event_type="CustomerPreferencesUpdated",
        payload=prefs,
    )
    db.flush()
    return prefs


def escalate_to_human_specialist(
    db: Session,
    claim: Claim,
    *,
    actor: UserContext,
    reason_category: str,
    notes: str,
    preferred_language: Optional[str] = None,
    preferred_channel: Optional[str] = None,
) -> dict[str, Any]:
    customer = db.query(Customer).filter(Customer.id == claim.customer_id).first() if claim.customer_id else None
    prefs = _resolve_preferences(claim, customer)
    lang = preferred_language if preferred_language in _LOCALIZED_STAGE_TITLES else prefs["preferred_language"]
    req_channel = preferred_channel if preferred_channel in SUPPORTED_CHANNELS else prefs["preferred_channel"]
    eff_channel, wa_blocked, _ = resolve_effective_channel(req_channel, prefs)

    now = datetime.now(timezone.utc)
    due_at = now + timedelta(hours=4)
    assigned_role = "claims_manager" if (claim.risk_tier == "HIGH" or reason_category in {"surveyor_delay", "settlement_dispute"}) else "claims_handler"

    task = ClaimTask(
        tenant_id=claim.tenant_id,
        claim_id=claim.id,
        task_type="customer_human_escalation",
        title=f"Customer Escalation ({reason_category.replace('_', ' ')}): {claim.claim_number}",
        description=notes or f"Policyholder requested direct human specialist callback ({reason_category}).",
        assigned_role=assigned_role,
        created_by_agent="customer_communication",
        priority="critical" if assigned_role == "claims_manager" else "high",
        status="open",
        reason_code=f"CUSTOMER_ESCALATION_{reason_category.upper()}",
        due_at=due_at,
        metadata_json={
            "reason_category": reason_category,
            "requested_by": actor.user_id,
            "callback_language": lang,
            "callback_channel": eff_channel,
            "sla_hours": 4,
        },
    )
    db.add(task)
    db.flush()

    esc_ref = f"ESC-{task.id[:8].upper()}"
    ack = compose_state_aware_message(
        "human_escalation_ack",
        lang,
        {
            "claim_number": claim.claim_number,
            "vehicle_reg": claim.vehicle_reg_input,
            "escalation_ref": esc_ref,
            "escalation_reason": reason_category.replace("_", " "),
        },
    )

    from services.integrations.adapters import IntegrationAdapterRegistry

    wa_msg_id = None
    delivery_status = "sent_mock"
    if eff_channel == "whatsapp":
        wa_res = IntegrationAdapterRegistry.send_whatsapp_message(
            phone_masked=prefs["phone_masked"],
            language=lang,
            template_id="CUSTOMER_HUMAN_ESCALATION_ACK",
            body=ack["body"],
            consent_whatsapp=prefs["consent_whatsapp"],
        )
        wa_msg_id = wa_res.get("whatsapp_message_id")
        delivery_status = str(wa_res.get("status", "delivered_whatsapp_mock"))

    comm = Communication(
        tenant_id=claim.tenant_id,
        claim_id=claim.id,
        channel=eff_channel,
        language=lang,
        template_id="CUSTOMER_HUMAN_ESCALATION_ACK",
        trigger_event="human_escalation_ack",
        claim_state_snapshot=claim.status,
        subject=ack["subject"][:240],
        body=ack["body"],
        requires_human_review=False,
        approved_by="system:escalation_ack",
        delivery_status=delivery_status,
        consent_verified=not wa_blocked,
        whatsapp_message_id=wa_msg_id,
        context_summary={"escalation_ref": esc_ref, "reason_category": reason_category, "assigned_role": assigned_role},
    )
    db.add(comm)
    emit_outbox_event(
        db,
        tenant_id=claim.tenant_id,
        aggregate_id=claim.id,
        event_type="CustomerHumanEscalationRequested",
        payload={"task_id": task.id, "escalation_ref": esc_ref, "reason_category": reason_category, "assigned_role": assigned_role},
    )
    record_audit_event(
        db,
        tenant_id=claim.tenant_id,
        claim_id=claim.id,
        actor_id=actor.user_id,
        actor_role=actor.role.value,
        action="CUSTOMER_ESCALATED_TO_HUMAN",
        object_type="claim_task",
        object_id=task.id,
        details={"escalation_ref": esc_ref, "reason_category": reason_category, "assigned_role": assigned_role, "callback_channel": eff_channel},
    )
    db.flush()
    return {
        "escalation_ref": esc_ref,
        "task_id": task.id,
        "assigned_role": assigned_role,
        "sla_callback_due_at": due_at.isoformat(),
        "callback_language": lang,
        "callback_channel": eff_channel,
        "whatsapp_blocked_no_consent": wa_blocked,
        "confirmation_subject": ack["subject"],
        "confirmation_message": ack["body"],
        "communication_id": comm.id,
    }
