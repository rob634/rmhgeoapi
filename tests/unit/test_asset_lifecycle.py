"""
Asset lifecycle method tests.

Anti-overfitting: Every ApprovalState tested against every lifecycle method.
Count assertions verify exact set properties.
"""

import pytest

from core.models.asset import AssetRelease, ApprovalState
from tests.factories.model_factories import make_asset_release


ALL_APPROVAL_STATES = list(ApprovalState)


# ============================================================================
# TestCanApprove
# ============================================================================

class TestCanApprove:
    """Only PENDING_REVIEW allows approval."""

    @pytest.mark.parametrize("state", ALL_APPROVAL_STATES,
                             ids=[s.value for s in ALL_APPROVAL_STATES])
    def test_can_approve_for_each_state(self, state):
        release = AssetRelease(**make_asset_release(approval_state=state))
        expected = (state == ApprovalState.PENDING_REVIEW)
        assert release.can_approve() == expected


# ============================================================================
# TestCanReject
# ============================================================================

class TestCanReject:
    """Only PENDING_REVIEW allows rejection."""

    @pytest.mark.parametrize("state", ALL_APPROVAL_STATES,
                             ids=[s.value for s in ALL_APPROVAL_STATES])
    def test_can_reject_for_each_state(self, state):
        release = AssetRelease(**make_asset_release(approval_state=state))
        expected = (state == ApprovalState.PENDING_REVIEW)
        assert release.can_reject() == expected


# ============================================================================
# TestCanRevoke
# ============================================================================

class TestCanRevoke:
    """Only APPROVED allows revocation."""

    @pytest.mark.parametrize("state", ALL_APPROVAL_STATES,
                             ids=[s.value for s in ALL_APPROVAL_STATES])
    def test_can_revoke_for_each_state(self, state):
        release = AssetRelease(**make_asset_release(approval_state=state))
        expected = (state == ApprovalState.APPROVED)
        assert release.can_revoke() == expected


# ============================================================================
# TestCanOverwrite
# ============================================================================

class TestCanOverwrite:
    """PENDING_REVIEW and REJECTED allow overwrite."""

    @pytest.mark.parametrize("state", ALL_APPROVAL_STATES,
                             ids=[s.value for s in ALL_APPROVAL_STATES])
    def test_can_overwrite_for_each_state(self, state):
        release = AssetRelease(**make_asset_release(approval_state=state))
        expected = state in (ApprovalState.PENDING_REVIEW, ApprovalState.REJECTED)
        assert release.can_overwrite() == expected


# ============================================================================
# TestIsDraft
# ============================================================================

class TestIsDraft:
    """Draft = version_id is None."""

    def test_no_version_id_is_draft(self):
        release = AssetRelease(**make_asset_release(version_id=None))
        assert release.is_draft() is True

    def test_with_version_id_not_draft(self):
        release = AssetRelease(**make_asset_release(version_id="v1"))
        assert release.is_draft() is False

    def test_ordinal_zero_with_no_version_is_draft(self):
        release = AssetRelease(
            **make_asset_release(version_id=None, version_ordinal=0)
        )
        assert release.is_draft() is True

    def test_ordinal_nonzero_with_no_version_is_still_draft(self):
        """Ordinal is set at creation but version_id assigned at approval."""
        release = AssetRelease(
            **make_asset_release(version_id=None, version_ordinal=1)
        )
        assert release.is_draft() is True

    def test_ordinal_nonzero_with_version_is_not_draft(self):
        release = AssetRelease(
            **make_asset_release(version_id="v2", version_ordinal=2)
        )
        assert release.is_draft() is False


# ============================================================================
# TestLifecycleSetProperties
# ============================================================================

class TestLifecycleSetProperties:
    """Count assertions on lifecycle method results across all states."""

    def test_exactly_one_state_allows_approval(self):
        count = sum(
            1 for state in ALL_APPROVAL_STATES
            if AssetRelease(**make_asset_release(approval_state=state)).can_approve()
        )
        assert count == 1

    def test_exactly_one_state_allows_revocation(self):
        count = sum(
            1 for state in ALL_APPROVAL_STATES
            if AssetRelease(**make_asset_release(approval_state=state)).can_revoke()
        )
        assert count == 1

    def test_exactly_two_states_allow_overwrite(self):
        count = sum(
            1 for state in ALL_APPROVAL_STATES
            if AssetRelease(**make_asset_release(approval_state=state)).can_overwrite()
        )
        assert count == 2

    def test_approve_states_subset_of_reject_states(self):
        """States allowing approve are a subset of states allowing reject."""
        approvable = {
            s for s in ALL_APPROVAL_STATES
            if AssetRelease(**make_asset_release(approval_state=s)).can_approve()
        }
        rejectable = {
            s for s in ALL_APPROVAL_STATES
            if AssetRelease(**make_asset_release(approval_state=s)).can_reject()
        }
        assert approvable <= rejectable

    def test_revokable_and_overwritable_are_disjoint(self):
        """You can't revoke AND overwrite the same state."""
        revokable = {
            s for s in ALL_APPROVAL_STATES
            if AssetRelease(**make_asset_release(approval_state=s)).can_revoke()
        }
        overwritable = {
            s for s in ALL_APPROVAL_STATES
            if AssetRelease(**make_asset_release(approval_state=s)).can_overwrite()
        }
        assert revokable & overwritable == set()
