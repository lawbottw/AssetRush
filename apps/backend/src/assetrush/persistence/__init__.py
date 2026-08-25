"""Database persistence contracts kept outside the pure game engine."""

from assetrush.persistence.state_codec import state_from_dict, state_to_dict

__all__ = ["state_from_dict", "state_to_dict"]
