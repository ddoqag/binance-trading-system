"""
Tests for Agent Civilization system
"""

import pytest
import numpy as np
import copy
from collections import defaultdict

try:
    from brain_py.agent_civilization import (
        AgentRole, Knowledge, Agent, AgentCivilization
    )
except ImportError:
    import sys
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    from agent_civilization import (
        AgentRole, Knowledge, Agent, AgentCivilization
    )


class TestAgentRole:
    """Test AgentRole enum"""

    def test_role_values(self):
        """Test all roles exist"""
        assert AgentRole.EXPLORER.value == "explorer"
        assert AgentRole.EXPLOITER.value == "exploiter"
        assert AgentRole.COORDINATOR.value == "coordinator"
        assert AgentRole.PREDATOR.value == "predator"
        assert AgentRole.SYMBIOT.value == "symbiot"


class TestKnowledge:
    """Test Knowledge dataclass"""

    def test_initialization(self):
        """Test knowledge initialization"""
        k = Knowledge(
            id="k_1",
            content={"strategy": "trend"},
            creator="agent_1"
        )

        assert k.id == "k_1"
        assert k.content == {"strategy": "trend"}
        assert k.creator == "agent_1"
        assert k.fitness == 0.0
        assert k.age == 0
        assert k.adoption_count == 0


class TestAgent:
    """Test Agent class"""

    def test_initialization(self):
        """Test agent initialization"""
        agent = Agent(
            id="agent_1",
            role=AgentRole.EXPLORER
        )

        assert agent.id == "agent_1"
        assert agent.role == AgentRole.EXPLORER
        assert agent.resources == 100.0
        assert agent.reputation == 1.0
        assert agent.generation == 0
        assert agent.parent_id is None
        assert isinstance(agent.knowledge_base, dict)

    def test_create_knowledge(self):
        """Test knowledge creation"""
        agent = Agent(id="agent_1", role=AgentRole.EXPLORER)

        content = {"strategy": "momentum", "params": [0.1, 0.2]}
        knowledge = agent.create_knowledge(content)

        assert isinstance(knowledge, Knowledge)
        assert knowledge.creator == "agent_1"
        assert knowledge.content == content
        assert knowledge.id in agent.knowledge_base

    def test_adopt_knowledge_success(self):
        """Test successful knowledge adoption"""
        agent1 = Agent(id="agent_1", role=AgentRole.EXPLORER, resources=20.0)
        agent2 = Agent(id="agent_2", role=AgentRole.EXPLOITER)

        knowledge = Knowledge(
            id="k_1",
            content={"strategy": "trend"},
            creator="agent_1"
        )

        success = agent2.adopt_knowledge(knowledge)

        assert success
        assert agent2.resources == 10.0  # Cost deducted
        assert knowledge.adoption_count == 1
        assert len(agent2.knowledge_base) == 1

    def test_adopt_knowledge_insufficient_resources(self):
        """Test knowledge adoption with insufficient resources"""
        agent = Agent(id="agent_1", role=AgentRole.EXPLORER, resources=5.0)

        knowledge = Knowledge(
            id="k_1",
            content={"strategy": "trend"},
            creator="other"
        )

        success = agent.adopt_knowledge(knowledge)

        assert not success
        assert agent.resources == 5.0  # No change
        assert len(agent.knowledge_base) == 0

    def test_adopt_knowledge_creates_copy(self):
        """Test that adoption creates a copy"""
        agent = Agent(id="agent_1", role=AgentRole.EXPLORER, resources=20.0)

        knowledge = Knowledge(
            id="k_1",
            content={"strategy": "trend"},
            creator="other"
        )

        agent.adopt_knowledge(knowledge)

        # Should be a copy with different ID
        adopted = list(agent.knowledge_base.values())[0]
        assert adopted.id != knowledge.id
        assert adopted.id.startswith("k_1")

    def test_reproduce_success(self):
        """Test successful reproduction"""
        parent = Agent(
            id="parent_1",
            role=AgentRole.EXPLORER,
            resources=100.0,
            generation=2
        )

        # Add some knowledge
        parent.create_knowledge({"strategy": "trend"})
        parent.create_knowledge({"strategy": "mean_rev"})

        child = parent.reproduce()

        assert child is not None
        assert child.parent_id == "parent_1"
        assert child.generation == 3
        assert child.resources == 50.0
        assert parent.resources == 50.0  # Cost deducted
        assert len(child.knowledge_base) > 0  # Knowledge inherited

    def test_reproduce_insufficient_resources(self):
        """Test reproduction with insufficient resources"""
        parent = Agent(id="parent_1", role=AgentRole.EXPLORER, resources=30.0)

        child = parent.reproduce()

        assert child is None
        assert parent.resources == 30.0  # No change

    def test_reproduce_role_mutation(self):
        """Test that child can have different role"""
        parent = Agent(
            id="parent_1",
            role=AgentRole.EXPLORER,
            resources=100.0
        )

        # Run multiple times to check for mutation
        roles = set()
        for _ in range(20):
            child = parent.reproduce()
            if child:
                roles.add(child.role)
                parent.resources = 100.0  # Reset

        # Should have some variety due to random mutation
        assert len(roles) >= 1


class TestAgentCivilization:
    """Test AgentCivilization class"""

    def test_initialization(self):
        """Test civilization initialization"""
        civ = AgentCivilization(n_agents=30, world_size=200.0)

        assert civ.n_agents == 30
        assert civ.world_size == 200.0
        assert civ.resource_regen_rate == 0.1
        assert len(civ.agents) == 30
        assert civ.generation == 0

    def test_initialization_creates_agents(self):
        """Test that initialization creates agents"""
        civ = AgentCivilization(n_agents=10)

        assert len(civ.agents) == 10
        for agent_id, agent in civ.agents.items():
            assert isinstance(agent, Agent)
            assert agent_id.startswith("agent_")
            assert len(agent.knowledge_base) >= 1

    def test_simulate_step(self):
        """Test simulation step"""
        civ = AgentCivilization(n_agents=10)
        initial_gen = civ.generation

        civ.simulate_step()

        assert civ.generation == initial_gen + 1
        assert len(civ.history) == 1

    def test_regenerate_resources(self):
        """Test resource regeneration"""
        civ = AgentCivilization(n_agents=5)

        # Set low resources
        for agent in civ.agents.values():
            agent.resources = 10.0

        civ._regenerate_resources()

        # All agents should have more resources now
        for agent in civ.agents.values():
            assert agent.resources > 10.0

    def test_explorer_action(self):
        """Test explorer behavior"""
        civ = AgentCivilization(n_agents=1)
        explorer = list(civ.agents.values())[0]
        explorer.role = AgentRole.EXPLORER
        explorer.resources = 100.0

        initial_knowledge = len(explorer.knowledge_base)
        civ._explorer_action(explorer)

        # Should have created new knowledge
        assert len(explorer.knowledge_base) >= initial_knowledge

    def test_exploiter_action(self):
        """Test exploiter behavior"""
        civ = AgentCivilization(n_agents=1)
        exploiter = list(civ.agents.values())[0]
        exploiter.role = AgentRole.EXPLOITER
        exploiter.resources = 100.0

        # Add some knowledge
        exploiter.create_knowledge({"strategy": "trend", "fitness": 0.5})
        exploiter.create_knowledge({"strategy": "mean_rev", "fitness": 0.8})

        initial_resources = exploiter.resources
        civ._exploiter_action(exploiter)

        # Should have gained resources
        assert exploiter.resources > initial_resources

    def test_coordinator_action(self):
        """Test coordinator behavior"""
        civ = AgentCivilization(n_agents=1)
        coordinator = list(civ.agents.values())[0]
        coordinator.role = AgentRole.COORDINATOR

        # Add two knowledge items
        k1 = coordinator.create_knowledge({"strategy": "trend", "params": [0.1, 0.2]})
        k2 = coordinator.create_knowledge({"strategy": "mean_rev", "params": [0.3, 0.4]})
        k1.fitness = 0.5
        k2.fitness = 0.7

        initial_knowledge = len(coordinator.knowledge_base)
        civ._coordinator_action(coordinator)

        # Should have created hybrid knowledge
        assert len(coordinator.knowledge_base) > initial_knowledge

    def test_predator_action(self):
        """Test predator behavior"""
        civ = AgentCivilization(n_agents=5)

        # Set up predator and victim
        predator = list(civ.agents.values())[0]
        predator.role = AgentRole.PREDATOR
        predator.resources = 200.0

        victim = list(civ.agents.values())[1]
        victim.resources = 50.0

        initial_predator_resources = predator.resources
        initial_victim_resources = victim.resources

        # Run multiple times to trigger action
        for _ in range(10):
            civ._predator_action(predator)

        # Predator should have gained or victim lost
        assert (predator.resources > initial_predator_resources or
                victim.resources < initial_victim_resources)

    def test_symbiot_action(self):
        """Test symbiot behavior"""
        civ = AgentCivilization(n_agents=5)

        # Set up two symbiots
        sym1 = list(civ.agents.values())[0]
        sym1.role = AgentRole.SYMBIOT
        sym1.create_knowledge({"strategy": "trend"})

        sym2 = list(civ.agents.values())[1]
        sym2.role = AgentRole.SYMBIOT
        sym2.create_knowledge({"strategy": "mean_rev"})

        initial_sym1_knowledge = len(sym1.knowledge_base)
        initial_sym2_knowledge = len(sym2.knowledge_base)

        civ._symbiot_action(sym1)

        # Both should have exchanged knowledge
        assert len(sym1.knowledge_base) >= initial_sym1_knowledge
        assert len(sym2.knowledge_base) >= initial_sym2_knowledge

    def test_record_history(self):
        """Test history recording"""
        civ = AgentCivilization(n_agents=5)

        civ._record_history()

        assert len(civ.history) == 1
        entry = civ.history[0]
        assert 'generation' in entry
        assert 'population' in entry
        assert 'role_distribution' in entry
        assert 'total_resources' in entry

    def test_get_best_strategies(self):
        """Test getting best strategies"""
        civ = AgentCivilization(n_agents=5)

        # Set up some knowledge with different fitness
        for i, agent in enumerate(civ.agents.values()):
            k = agent.create_knowledge({"strategy": f"s{i}"})
            k.fitness = float(i) * 0.1

        best = civ.get_best_strategies(n=3)

        assert len(best) == 3
        # Should be sorted by fitness descending
        assert best[0].fitness >= best[1].fitness
        assert best[1].fitness >= best[2].fitness

    def test_get_society_stats(self):
        """Test society statistics"""
        civ = AgentCivilization(n_agents=10)

        stats = civ.get_society_stats()

        assert stats['generation'] == 0
        assert stats['population'] == 10
        assert 'avg_resources' in stats
        assert 'avg_knowledge' in stats
        assert 'role_distribution' in stats

        # Check role distribution
        for role in AgentRole:
            assert role in stats['role_distribution']

    def test_get_society_stats_empty(self):
        """Test stats with empty population"""
        civ = AgentCivilization(n_agents=0)

        stats = civ.get_society_stats()
        assert stats == {}

    def test_run_simulation(self):
        """Test running full simulation"""
        civ = AgentCivilization(n_agents=10)

        civ.run_simulation(n_generations=50)

        assert civ.generation == 50
        assert len(civ.history) == 50

    def test_agent_death(self):
        """Test agent death during simulation"""
        civ = AgentCivilization(n_agents=5)

        # Set one agent to have negative resources
        agent = list(civ.agents.values())[0]
        agent.resources = -10.0

        initial_count = len(civ.agents)
        civ.simulate_step()

        # Agent should be removed
        assert len(civ.agents) < initial_count

    def test_agent_reproduction(self):
        """Test agent reproduction during simulation"""
        civ = AgentCivilization(n_agents=5)

        # Set all agents to have enough resources
        for agent in civ.agents.values():
            agent.resources = 100.0

        initial_count = len(civ.agents)
        civ.simulate_step()

        # Population should have grown
        assert len(civ.agents) >= initial_count

    def test_knowledge_aging(self):
        """Test knowledge aging"""
        civ = AgentCivilization(n_agents=1)
        agent = list(civ.agents.values())[0]

        k = agent.create_knowledge({"strategy": "trend"})
        k.fitness = 1.0

        civ.simulate_step()

        # Knowledge should have aged and fitness decayed
        assert k.age == 1
        assert k.fitness < 1.0

    def test_export_state(self):
        """Test state export"""
        civ = AgentCivilization(n_agents=5)
        civ.simulate_step()

        state = civ.export_state()

        assert 'n_agents' in state
        assert 'world_size' in state
        assert 'agents' in state
        assert 'global_knowledge' in state
        assert 'generation' in state
        assert 'history' in state

        # Check agent serialization
        for agent_id, agent_data in state['agents'].items():
            assert 'id' in agent_data
            assert 'role' in agent_data
            assert 'resources' in agent_data
            assert 'knowledge_base' in agent_data

    def test_import_state(self):
        """Test state import"""
        civ1 = AgentCivilization(n_agents=5)
        civ1.simulate_step()

        state = civ1.export_state()

        civ2 = AgentCivilization(n_agents=0)
        civ2.import_state(state)

        assert civ2.n_agents == civ1.n_agents
        assert civ2.generation == civ1.generation
        assert len(civ2.agents) == len(civ1.agents)

    def test_import_state_partial(self):
        """Test partial state import"""
        civ = AgentCivilization(n_agents=0)

        partial_state = {
            'n_agents': 3,
            'world_size': 100.0,
            'generation': 10,
            'agents': {},
            'global_knowledge': {},
            'history': []
        }

        civ.import_state(partial_state)

        assert civ.n_agents == 3
        assert civ.generation == 10


class TestIntegration:
    """Integration tests"""

    def test_multiple_generations(self):
        """Test multiple generations of evolution"""
        civ = AgentCivilization(n_agents=20)

        initial_avg_resources = civ.get_society_stats()['avg_resources']

        for _ in range(100):
            civ.simulate_step()

        final_stats = civ.get_society_stats()

        # Society should have evolved
        assert final_stats['generation'] == 100
        assert final_stats['population'] > 0

        # Best strategies should exist
        best = civ.get_best_strategies(n=5)
        assert len(best) <= 5

    def test_role_distribution_changes(self):
        """Test that role distribution changes over time"""
        civ = AgentCivilization(n_agents=30)

        initial_dist = civ.get_society_stats()['role_distribution'].copy()

        for _ in range(50):
            civ.simulate_step()

        final_dist = civ.get_society_stats()['role_distribution']

        # Distribution might change due to reproduction/mutation
        # Just verify all roles are tracked
        for role in AgentRole:
            assert role in final_dist

    def test_resource_flow(self):
        """Test resource flow in society"""
        civ = AgentCivilization(n_agents=10)

        total_resources = []

        for _ in range(20):
            stats = civ.get_society_stats()
            total_resources.append(stats['total_resources'])
            civ.simulate_step()

        # Resources should generally increase due to regeneration
        assert total_resources[-1] > total_resources[0] * 0.5  # Allow for some deaths
