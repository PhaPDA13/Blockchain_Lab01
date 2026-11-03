"""
Consensus layer: BFT 2-phase consensus (Prevote and Precommit) with strict locking rules.
"""
from .vote import Vote, VoteType
from .rules import ConsensusLockState
from .engine import ConsensusEngine

__all__ = ["Vote", "VoteType", "ConsensusLockState", "ConsensusEngine"]
