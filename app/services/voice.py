"""
VOICE ESCALATION - THE BOUNDARY, DELIBERATELY NOT WALKED THROUGH YET.

ResQ's Android client today escalates a no-response incident by asking the phone
to place a normal SIM call to the user's primary contact. That path is unaffected
by anything in this module and does not import it.

This module exists so that a FUTURE cloud-call provider has a defined, reviewable
interface to implement - and so that the decisions that are expensive to get wrong
are made now, while nothing depends on them:

  * the BACKEND holds provider credentials. The APK never sees an account SID, an
    auth token, or a provider SDK;
  * a request is only ever a REQUEST. The response says the provider accepted it.
    It never says a message was spoken, a call connected, or a human answered,
    because this backend cannot know that from an HTTP call;
  * the emergency number is refused unconditionally. Cloud voice calls to 112 are
    not something this backend will ever dispatch;
  * consent is a precondition, recorded per request, and an absent record is a
    refusal rather than a default-allow;
  * duplicate suppression is idempotency-key based, so a retried request, a
    duplicate webhook, or a client reconnect can never produce two calls;
  * logs are privacy-safe by construction: incident id, state and provider error
    CODE. Never a phone number, never the spoken message, never a location.

WHAT IS NOT HERE, ON PURPOSE
---------------------------
There is no route, no HTTP endpoint, no provider SDK and no paid integration.
`VoiceEscalationProvider.is_available()` is False for the only implementation that
exists (`DisabledVoiceEscalationProvider`), so any attempt to use this raises
`VoiceEscalationDisabled` rather than silently doing nothing. Selecting and paying
for a provider is a product decision that has not been made.
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass, field
from typing import Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

#: Numbers this backend will never place a cloud voice call to, regardless of
#: consent or configuration. Emergency services must be reached by the phone
#: itself, where the user can hang up, and by the local jurisdiction's rules.
FORBIDDEN_DESTINATIONS = frozenset({"112", "911", "999", "1123", "000"})


class VoiceEscalationState(str, enum.Enum):
    """
    What the BACKEND can honestly assert about a voice request.

    The ladder is deliberately conservative: every state is something this
    backend verified, and none of them implies a person was reached.
    """

    #: The backend accepted the request and will hand it to the provider.
    ACCEPTED = "accepted"

    #: The provider accepted the call request. Still says nothing about delivery.
    PROVIDER_ACCEPTED = "provider_accepted"

    #: The provider reported the call ringing.
    RINGING = "ringing"

    #: The provider reported the call was answered by the far end. This is the
    #: strongest claim available, and it is still only a provider report.
    ANSWERED = "answered"

    #: The provider reported the call completed.
    COMPLETED = "completed"

    #: The provider refused, or the request was malformed.
    REJECTED = "rejected"

    #: The provider accepted nothing and the attempt failed.
    FAILED = "failed"

    #: The backend never attempted a call.
    NOT_ATTEMPTED = "not_attempted"


class VoiceEscalationOutcome(str, enum.Enum):
    """Whether a request may proceed at all. Evaluated before any provider call."""

    #: Proceed to the provider.
    PERMITTED = "permitted"

    #: The user has not consented to an automated voice call.
    CONSENT_MISSING = "consent_missing"

    #: No primary contact number was supplied.
    DESTINATION_MISSING = "destination_missing"

    #: The destination is an emergency number. Always refused.
    DESTINATION_FORBIDDEN = "destination_forbidden"

    #: No provider is selected or configured yet.
    PROVIDER_UNAVAILABLE = "provider_unavailable"


class VoiceEscalationError(RuntimeError):
    """Base class for every failure this module raises."""


class VoiceEscalationDisabled(VoiceEscalationError):
    """Raised when an escalation is attempted while no provider is selected."""


class VoiceEscalationRefused(VoiceEscalationError):
    """
    Raised when policy forbids the request (no consent, forbidden destination).

    Carries the machine-readable reason so a caller can report it without
    inspecting an exception message.
    """

    def __init__(self, outcome: VoiceEscalationOutcome) -> None:
        super().__init__(outcome.value)
        self.outcome = outcome


@dataclass(frozen=True)
class VoiceEscalationRequest:
    """
    One request to speak an emergency message to a consented primary contact.

    Carries NO provider credentials and NO location. The provider account lives
    in this backend's configuration; the app never holds it.
    """

    #: Stable identifier for the incident. Also the idempotency key: the same
    #: incident may be retried any number of times and must still produce at most
    #: one call.
    incident_id: str

    #: The consented primary contact, in E.164 form. Never logged.
    destination: str

    #: The message to speak. Never logged, and never sent to the app.
    message: str

    #: BCP-47 tag for the message language.
    locale: str = "en-IN"

    #: The user's recorded consent for an automated voice call. Required, and
    #: defaulted to False on purpose: an absent record must never mean "allow".
    consent_granted: bool = False

    #: When the incident happened. Recorded for the provider's own records.
    occurred_at: Optional[str] = None


@dataclass(frozen=True)
class VoiceEscalationResult:
    """
    The honest result of a request.

    [state] is what the backend can assert. [provider_reference] is the
    provider's own id, which a future status-callback endpoint would use - it is
    never sufficient on its own to claim a message was delivered.
    """

    incident_id: str
    outcome: VoiceEscalationOutcome
    state: VoiceEscalationState
    provider_reference: Optional[str] = None

    #: True only when the PROVIDER explicitly reported this state. It is never
    #: set by this backend inferring anything.
    provider_confirmed: bool = False

    @property
    def delivered(self) -> bool:
        """
        Whether a message may be described as delivered.

        Intentionally strict: a provider ACCEPTING a call request is not
        delivery, and only a provider-reported ANSWERED or COMPLETED is. Nothing
        in the UI may phrase an accepted request as a delivered message.
        """
        return self.provider_confirmed and self.state in (
            VoiceEscalationState.ANSWERED,
            VoiceEscalationState.COMPLETED,
        )


@dataclass(frozen=True)
class VoiceEscalationPolicy:
    """
    The rules every provider implementation is held to.

    A provider that cannot satisfy these is not a candidate, regardless of what
    its marketing says.
    """

    #: Whether the backend is willing to dispatch cloud voice calls at all. False
    #: until a provider has been selected, contracted and reviewed.
    enabled: bool = False

    #: Deduplication window. A repeat of the same incident id inside it is
    #: suppressed, so a client retry or a webhook replay cannot double-dial.
    duplicate_window_seconds: int = 900

    #: Hard ceiling on how many calls one incident may ever produce, including
    #: through provider retries.
    max_attempts_per_incident: int = 1

    #: Outcome codes that may appear in logs. Anything else is dropped rather
    #: than risk leaking a provider message that quotes user data.
    loggable_state_values: frozenset = field(
        default_factory=lambda: frozenset({state.value for state in VoiceEscalationState})
    )


@runtime_checkable
class VoiceEscalationProvider(Protocol):
    """
    THE MINIMAL INTERFACE A FUTURE PROVIDER MUST IMPLEMENT.

    A provider is only asked to do two things: report whether it can be used, and
    accept one call request. Status transitions arrive later through a callback
    this backend will own - never through the app.
    """

    @property
    def is_available(self) -> bool:
        """False while no provider is selected, configured or reachable."""

    async def place_voice_call(self, request: VoiceEscalationRequest) -> VoiceEscalationResult:
        """
        Ask the provider to place a call that speaks [VoiceEscalationRequest.message].

        Implementations must:
          - raise rather than fabricate a result when the call cannot be made;
          - never return a state the provider did not actually report;
          - never log the destination or the message;
          - treat the emergency number as an invalid destination.

        Deliberately absent from this interface: cancellation, media upload, and
        any way for the app to observe a call directly. None of them are needed
        for the escalation ResQ actually wants, and each one widens the surface a
        provider could misuse.
        """


class DisabledVoiceEscalationProvider:
    """
    The only implementation that exists, and it does nothing.

    Present so the rest of the codebase has something concrete to depend on and so
    the failure mode is explicit: asking for a cloud voice call today raises
    `VoiceEscalationDisabled` instead of returning a fake "accepted".
    """

    @property
    def is_available(self) -> bool:
        return False

    async def place_voice_call(self, request: VoiceEscalationRequest) -> VoiceEscalationResult:
        raise VoiceEscalationDisabled(
            "Cloud voice escalation is not enabled. No telephony provider has been "
            "selected, so ResQ escalates with the device's own cellular call."
        )


class VoiceEscalationService:
    """
    Policy in front of a provider: consent, destination safety, duplicate
    suppression, and honest reporting.

    Constructed with the disabled provider by default, so importing this module
    can never make ResQ capable of dispatching a cloud call.
    """

    def __init__(
        self,
        provider: Optional[VoiceEscalationProvider] = None,
        policy: Optional[VoiceEscalationPolicy] = None,
    ) -> None:
        self._provider = provider or DisabledVoiceEscalationProvider()
        self._policy = policy or VoiceEscalationPolicy()
        # incident_id -> state. In-memory on purpose: a duplicate must be
        # suppressed for the life of the incident, and ResQ's incident ids are
        # not reused after a restart.
        self._seen: dict[str, VoiceEscalationState] = {}

    @property
    def is_enabled(self) -> bool:
        return self._policy.enabled and self._provider.is_available

    def evaluate(self, request: VoiceEscalationRequest) -> VoiceEscalationOutcome:
        """
        Whether [request] may proceed. Pure, and evaluated BEFORE the provider is
        touched, so a refusal can never become a provider call.
        """
        if not self._policy.enabled:
            return VoiceEscalationOutcome.PROVIDER_UNAVAILABLE
        if not self._provider.is_available:
            return VoiceEscalationOutcome.PROVIDER_UNAVAILABLE
        if not request.consent_granted:
            return VoiceEscalationOutcome.CONSENT_MISSING
        if not request.destination.strip():
            return VoiceEscalationOutcome.DESTINATION_MISSING
        if _normalise_destination(request.destination) in FORBIDDEN_DESTINATIONS:
            return VoiceEscalationOutcome.DESTINATION_FORBIDDEN
        return VoiceEscalationOutcome.PERMITTED

    async def escalate(self, request: VoiceEscalationRequest) -> VoiceEscalationResult:
        """
        Attempt one voice escalation.

        Raises [VoiceEscalationDisabled] while no provider is selected, and
        [VoiceEscalationRefused] for a policy refusal on a live feature. Neither
        is ever swallowed into a success.
        """
        if not self.is_enabled:
            # A distinct exception from a policy refusal: this is the feature not
            # existing yet, not a user declining. ResQ's own cellular escalation is
            # unaffected and remains the escalation path.
            logger.info(
                "Voice escalation not attempted for incident %s: no provider enabled",
                request.incident_id,
            )
            raise VoiceEscalationDisabled(
                "Cloud voice escalation is not enabled. No telephony provider has "
                "been selected, so ResQ escalates with the device's own cellular "
                "call."
            )

        outcome = self.evaluate(request)
        if outcome is not VoiceEscalationOutcome.PERMITTED:
            # Logged by outcome only: no destination, no message, no coordinates.
            logger.info(
                "Voice escalation refused for incident %s: %s",
                request.incident_id,
                outcome.value,
            )
            raise VoiceEscalationRefused(outcome)

        existing = self._seen.get(request.incident_id)
        if existing is not None:
            # A duplicate is reported, not re-dispatched, and never reported as a
            # new provider acceptance.
            logger.info(
                "Voice escalation duplicate suppressed for incident %s (already %s)",
                request.incident_id,
                existing.value,
            )
            return VoiceEscalationResult(
                incident_id=request.incident_id,
                outcome=outcome,
                state=existing,
                provider_confirmed=False,
            )

        result = await self._provider.place_voice_call(request)
        self._seen[request.incident_id] = result.state
        logger.info(
            "Voice escalation dispatched for incident %s: state=%s confirmed=%s",
            request.incident_id,
            result.state.value,
            result.provider_confirmed,
        )
        return result

    def apply_status_callback(
        self,
        incident_id: str,
        state: VoiceEscalationState,
        provider_reference: Optional[str] = None,
    ) -> VoiceEscalationResult:
        """
        Record a status transition the PROVIDER reported.

        This is the only way a result may claim to be provider-confirmed. Nothing
        here infers a state: an unrecognised transition is stored as-is and never
        upgraded, because inventing progress is how a false "your message was
        delivered" claim would eventually be made.
        """
        if not self._policy.enabled:
            raise VoiceEscalationDisabled(
                "Voice escalation is not enabled, so no status callback is accepted."
            )
        self._seen[incident_id] = state
        return VoiceEscalationResult(
            incident_id=incident_id,
            outcome=VoiceEscalationOutcome.PERMITTED,
            state=state,
            provider_reference=provider_reference,
            # Confirmed only for a terminal state the provider could actually have
            # reported. Everything else stays unconfirmed.
            provider_confirmed=state
            in (VoiceEscalationState.ANSWERED, VoiceEscalationState.COMPLETED),
        )

    def forget_incident(self, incident_id: str) -> None:
        """Clears the duplicate ledger once an incident has definitively ended."""
        self._seen.pop(incident_id, None)


def _normalise_destination(destination: str) -> str:
    """
    Reduces a phone number to the form the forbidden list is written in.

    Strips separators, a leading "+" and a leading "00" so that "+112", "112",
    "1-1-2" and "00112" are all recognised as the emergency number. Getting this
    wrong would mean the one destination this must never reach is the one most
    likely to slip through.
    """
    digits = "".join(character for character in destination if character.isdigit())
    if digits.startswith("00"):
        digits = digits[2:]
    return digits