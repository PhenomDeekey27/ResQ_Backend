"""
TESTS FOR THE VOICE-ESCALATION BOUNDARY.

These assert the NEGATIVE requirements, which are the ones that matter while no
provider has been selected:

  - nothing dispatches by default;
  - the emergency number is never a valid destination, in any formatting;
  - consent is required and its absence is a refusal, not a default-allow;
  - a duplicate incident never produces a second dispatch;
  - no result claims delivery the provider did not report;
  - no status callback is accepted while the feature is disabled.

No network call is made, no phone number is dialled, and no test here can reach a
real telephony provider.
"""

import pytest

from app.services.voice import (
    DisabledVoiceEscalationProvider,
    VoiceEscalationDisabled,
    VoiceEscalationOutcome,
    VoiceEscalationPolicy,
    VoiceEscalationProvider,
    VoiceEscalationRefused,
    VoiceEscalationRequest,
    VoiceEscalationResult,
    VoiceEscalationService,
    VoiceEscalationState,
)

PRIMARY = "+919876543210"


def request(**overrides) -> VoiceEscalationRequest:
    base = dict(
        incident_id="incident-1",
        destination=PRIMARY,
        message="Priya may have had an accident. Please check on them.",
        consent_granted=True,
    )
    base.update(overrides)
    return VoiceEscalationRequest(**base)


class RecordingProvider:
    """A stand-in provider. It records dispatches instead of making calls."""

    def __init__(self, state=VoiceEscalationState.PROVIDER_ACCEPTED, available=True):
        self._state = state
        self._available = available
        self.calls = []

    @property
    def is_available(self) -> bool:
        return self._available

    async def place_voice_call(self, request: VoiceEscalationRequest) -> VoiceEscalationResult:
        self.calls.append(request)
        return VoiceEscalationResult(
            incident_id=request.incident_id,
            outcome=VoiceEscalationOutcome.PERMITTED,
            state=self._state,
            provider_reference="provider-ref-1",
            provider_confirmed=self._state
            in (VoiceEscalationState.ANSWERED, VoiceEscalationState.COMPLETED),
        )


def enabled_service(provider) -> VoiceEscalationService:
    return VoiceEscalationService(provider=provider, policy=VoiceEscalationPolicy(enabled=True))


class TestDisabledByDefault:
    def test_the_default_service_cannot_dispatch(self):
        service = VoiceEscalationService()

        assert service.is_enabled is False
        assert isinstance(service._provider, DisabledVoiceEscalationProvider)

    @pytest.mark.asyncio
    async def test_escalating_raises_rather_than_faking_success(self):
        service = VoiceEscalationService()

        with pytest.raises(VoiceEscalationDisabled):
            await service.escalate(request())

    def test_evaluation_reports_the_provider_as_unavailable(self):
        assert (
            VoiceEscalationService().evaluate(request())
            is VoiceEscalationOutcome.PROVIDER_UNAVAILABLE
        )

    @pytest.mark.asyncio
    async def test_the_disabled_provider_itself_raises(self):
        provider = DisabledVoiceEscalationProvider()

        assert provider.is_available is False
        with pytest.raises(VoiceEscalationDisabled):
            await provider.place_voice_call(request())

    def test_no_status_callback_is_accepted_while_disabled(self):
        with pytest.raises(VoiceEscalationDisabled):
            VoiceEscalationService().apply_status_callback(
                "incident-1", VoiceEscalationState.ANSWERED
            )

    def test_an_unavailable_provider_blocks_even_when_policy_is_enabled(self):
        provider = RecordingProvider(available=False)
        service = enabled_service(provider)

        assert service.is_enabled is False
        assert (
            service.evaluate(request())
            is VoiceEscalationOutcome.PROVIDER_UNAVAILABLE
        )


class TestConsentAndDestinationSafety:
    @pytest.mark.asyncio
    async def test_missing_consent_is_refused_and_never_dispatched(self):
        provider = RecordingProvider()
        service = enabled_service(provider)

        with pytest.raises(VoiceEscalationRefused) as raised:
            await service.escalate(request(consent_granted=False))

        assert raised.value.outcome is VoiceEscalationOutcome.CONSENT_MISSING
        assert provider.calls == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize("destination", ["112", "+112", "1-1-2", "00112", " 112 "])
    async def test_the_emergency_number_is_refused_in_every_formatting(self, destination):
        provider = RecordingProvider()
        service = enabled_service(provider)

        with pytest.raises(VoiceEscalationRefused) as raised:
            await service.escalate(request(destination=destination))

        assert raised.value.outcome is VoiceEscalationOutcome.DESTINATION_FORBIDDEN
        assert provider.calls == []

    @pytest.mark.asyncio
    async def test_a_missing_destination_is_refused(self):
        provider = RecordingProvider()
        service = enabled_service(provider)

        with pytest.raises(VoiceEscalationRefused) as raised:
            await service.escalate(request(destination="   "))

        assert raised.value.outcome is VoiceEscalationOutcome.DESTINATION_MISSING
        assert provider.calls == []

    @pytest.mark.asyncio
    async def test_a_consented_primary_contact_is_dispatched_once(self):
        provider = RecordingProvider()
        service = enabled_service(provider)

        result = await service.escalate(request())

        assert len(provider.calls) == 1
        assert result.state is VoiceEscalationState.PROVIDER_ACCEPTED


class TestDuplicateSuppression:
    @pytest.mark.asyncio
    async def test_retrying_one_incident_never_produces_a_second_call(self):
        provider = RecordingProvider()
        service = enabled_service(provider)

        first = await service.escalate(request())
        second = await service.escalate(request())

        assert len(provider.calls) == 1
        # The duplicate reports the existing state and does NOT claim the provider
        # confirmed a second delivery.
        assert second.state is first.state
        assert second.provider_confirmed is False

    @pytest.mark.asyncio
    async def test_a_different_incident_is_not_suppressed(self):
        provider = RecordingProvider()
        service = enabled_service(provider)

        await service.escalate(request(incident_id="incident-1"))
        await service.escalate(request(incident_id="incident-2"))

        assert len(provider.calls) == 2

    @pytest.mark.asyncio
    async def test_the_ledger_is_released_when_an_incident_ends(self):
        provider = RecordingProvider()
        service = enabled_service(provider)

        await service.escalate(request())
        service.forget_incident("incident-1")
        await service.escalate(request())

        assert len(provider.calls) == 2


class TestHonestReporting:
    def test_an_accepted_request_is_never_reported_as_delivered(self):
        result = VoiceEscalationResult(
            incident_id="incident-1",
            outcome=VoiceEscalationOutcome.PERMITTED,
            state=VoiceEscalationState.PROVIDER_ACCEPTED,
            provider_confirmed=False,
        )

        assert result.delivered is False

    def test_a_provider_reported_answer_is_deliverable(self):
        result = VoiceEscalationResult(
            incident_id="incident-1",
            outcome=VoiceEscalationOutcome.PERMITTED,
            state=VoiceEscalationState.ANSWERED,
            provider_confirmed=True,
        )

        assert result.delivered is True

    def test_an_unconfirmed_terminal_state_is_not_delivery(self):
        result = VoiceEscalationResult(
            incident_id="incident-1",
            outcome=VoiceEscalationOutcome.PERMITTED,
            state=VoiceEscalationState.COMPLETED,
            provider_confirmed=False,
        )

        assert result.delivered is False

    def test_a_status_callback_confirms_only_a_terminal_state(self):
        provider = RecordingProvider()
        service = enabled_service(provider)

        ringing = service.apply_status_callback(
            "incident-1", VoiceEscalationState.RINGING, "ref-1"
        )
        answered = service.apply_status_callback(
            "incident-1", VoiceEscalationState.ANSWERED, "ref-1"
        )

        assert ringing.provider_confirmed is False
        assert ringing.delivered is False
        assert answered.provider_confirmed is True
        assert answered.delivered is True

    @pytest.mark.asyncio
    async def test_a_provider_failure_never_becomes_a_delivery(self):
        provider = RecordingProvider(state=VoiceEscalationState.FAILED)
        service = enabled_service(provider)

        result = await service.escalate(request())

        assert result.state is VoiceEscalationState.FAILED
        assert result.provider_confirmed is False
        assert result.delivered is False


class TestInterface:
    def test_the_recording_provider_satisfies_the_protocol(self):
        assert isinstance(RecordingProvider(), VoiceEscalationProvider)

    def test_the_default_policy_is_off(self):
        assert VoiceEscalationPolicy().enabled is False

    def test_one_call_per_incident_is_the_configured_ceiling(self):
        assert VoiceEscalationPolicy().max_attempts_per_incident == 1