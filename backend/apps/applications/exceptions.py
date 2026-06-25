from apps.common.exceptions import DomainError


class InvalidTransitionError(DomainError):
    """Action is not valid for the milestone's current status or sequence position."""


class SeparationOfDutiesError(DomainError):
    """AC-09: Acting officer is an ApplicationParty and may not act on this milestone."""


class ConcurrentModificationError(DomainError):
    """AC-02: Milestone was already processed by a concurrent request."""
