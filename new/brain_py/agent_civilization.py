"""
agent_civilization.py - Phase 9: Agent Civilization

策略社会进化系统:
1. 多智能体社会模拟
2. 策略竞争与合作
3. 知识传递和学习
4. 生态系统演化
"""

import numpy as np
import random
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field
from enum import Enum, auto
from collections import defaultdict, deque
import copy


class AgentRole(Enum):
    """智能体角色"""
    EXPLORER = "explorer"      # 探索者 - 发现新策略
    EXPLOITER = "exploiter"    # 利用者 - 优化已知策略
    COORDINATOR = "coordinator" # 协调者 - 整合多策略
    PREDATOR = "predator"      # 捕食者 - 套利其他策略
    SYMBIOT = "symbiot"        # 共生者 - 合作共赢


@dataclass
class Knowledge:
    """知识片段"""
    id: str
    content: Dict  # 策略参数、规则等
    creator: str
    fitness: float = 0.0
    age: int = 0
    adoption_count: int = 0


@dataclass
class Agent:
    """文明智能体"""
    id: str
    role: AgentRole
    knowledge_base: Dict[str, Knowledge] = field(default_factory=dict)
    resources: float = 100.0  # 资源/财富
    reputation: float = 1.0   # 声誉
    generation: int = 0
    parent_id: Optional[str] = None

    def create_knowledge(self, content: Dict) -> Knowledge:
        """创造新知识"""
        knowledge = Knowledge(
            id=f"k_{self.id}_{len(self.knowledge_base)}",
            content=content,
            creator=self.id
        )
        self.knowledge_base[knowledge.id] = knowledge
        return knowledge

    def adopt_knowledge(self, knowledge: Knowledge) -> bool:
        """采纳他人知识"""
        if self.resources >= 10:  # 学习成本
            self.resources -= 10
            knowledge.adoption_count += 1

            # 复制到知识库
            local_copy = copy.deepcopy(knowledge)
            local_copy.id = f"{knowledge.id}_copy_{self.id}"
            self.knowledge_base[local_copy.id] = local_copy
            return True
        return False

    def reproduce(self) -> Optional['Agent']:
        """繁殖 (资源足够时)"""
        if self.resources >= 50:
            self.resources -= 50

            # 创建后代
            child = Agent(
                id=f"{self.id}_child_{random.randint(1000, 9999)}",
                role=random.choice(list(AgentRole)),  # 可能变异
                resources=50,
                generation=self.generation + 1,
                parent_id=self.id
            )

            # 传递部分知识
            for k_id, knowledge in list(self.knowledge_base.items())[:3]:
                child.knowledge_base[k_id] = copy.deepcopy(knowledge)

            return child
        return None


class AgentCivilization:
    """
    智能体文明系统

    模拟策略社会的进化:
    - 智能体有自己的角色和策略
    - 通过交易/竞争/合作获取资源
    - 知识和策略在社会中传播
    - 适者生存，不适者淘汰
    """

    def __init__(
        self,
        n_agents: int = 50,
        world_size: float = 100.0,
        resource_regen_rate: float = 0.1
    ):
        self.n_agents = n_agents
        self.world_size = world_size
        self.resource_regen_rate = resource_regen_rate

        self.agents: Dict[str, Agent] = {}
        self.global_knowledge: Dict[str, Knowledge] = {}
        self.market_prices: Dict[str, float] = defaultdict(float)

        self.generation = 0
        self.history: deque = deque(maxlen=500)  # 限制历史记录大小

        self._initialize_population()

    def _initialize_population(self):
        """初始化种群"""
        roles = list(AgentRole)

        for i in range(self.n_agents):
            agent = Agent(
                id=f"agent_{i}",
                role=random.choice(roles),
                resources=random.uniform(50, 150)
            )

            # 初始知识
            for j in range(random.randint(1, 3)):
                agent.create_knowledge({
                    'strategy_type': random.choice(['trend', 'mean_rev', 'momentum']),
                    'params': np.random.randn(5).tolist()
                })

            self.agents[agent.id] = agent

    def simulate_step(self):
        """模拟一步"""
        # 1. 资源再生
        self._regenerate_resources()

        # 2. 智能体互动
        for agent in list(self.agents.values()):
            if agent.resources <= 0:
                continue

            # 根据角色行动
            if agent.role == AgentRole.EXPLORER:
                self._explorer_action(agent)
            elif agent.role == AgentRole.EXPLOITER:
                self._exploiter_action(agent)
            elif agent.role == AgentRole.COORDINATOR:
                self._coordinator_action(agent)
            elif agent.role == AgentRole.PREDATOR:
                self._predator_action(agent)
            elif agent.role == AgentRole.SYMBIOT:
                self._symbiot_action(agent)

        # 3. 繁殖
        new_agents = []
        for agent in self.agents.values():
            child = agent.reproduce()
            if child:
                new_agents.append(child)

        for child in new_agents:
            self.agents[child.id] = child

        # 4. 淘汰
        dead_agents = [
            aid for aid, a in self.agents.items()
            if a.resources <= 0 or random.random() < 0.01  # 1% 随机死亡
        ]
        for aid in dead_agents:
            del self.agents[aid]

        # 5. 知识老化
        for agent in self.agents.values():
            for knowledge in agent.knowledge_base.values():
                knowledge.age += 1
                knowledge.fitness *= 0.99  # 衰减

        # 记录历史
        self._record_history()
        self.generation += 1

    def _regenerate_resources(self):
        """资源再生"""
        for agent in self.agents.values():
            base_income = 5.0
            knowledge_bonus = len(agent.knowledge_base) * 2
            agent.resources += base_income + knowledge_bonus

    def _explorer_action(self, agent: Agent):
        """探索者行为 - 创造新知识"""
        # 创造新策略
        new_knowledge = agent.create_knowledge({
            'strategy_type': 'novel',
            'params': np.random.randn(5).tolist(),
            'novelty': random.random()
        })

        # 可能获得高回报
        if random.random() < 0.1:  # 10% 发现好东西
            agent.resources += 100
            new_knowledge.fitness = 1.0

    def _exploiter_action(self, agent: Agent):
        """利用者行为 - 优化已有知识"""
        if agent.knowledge_base:
            # 改进现有知识
            best_k = max(agent.knowledge_base.values(), key=lambda k: k.fitness)
            best_k.fitness += 0.1
            agent.resources += 20 * best_k.fitness

    def _coordinator_action(self, agent: Agent):
        """协调者行为 - 整合知识"""
        if len(agent.knowledge_base) >= 2:
            # 组合两个知识
            k_list = list(agent.knowledge_base.values())
            k1, k2 = random.sample(k_list, 2)

            combined = agent.create_knowledge({
                'strategy_type': 'hybrid',
                'parent_knowledge': [k1.id, k2.id],
                'params': [(a + b) / 2 for a, b in zip(k1.content['params'], k2.content['params'])]
            })
            combined.fitness = (k1.fitness + k2.fitness) / 2 + 0.1

            agent.resources += 30 * combined.fitness

    def _predator_action(self, agent: Agent):
        """捕食者行为 - 从弱者获取资源"""
        # 找到弱者
        weaker = [
            a for a in self.agents.values()
            if a.id != agent.id and a.resources < agent.resources * 0.5
        ]

        if weaker and random.random() < 0.3:
            target = random.choice(weaker)
            stolen = target.resources * 0.2
            target.resources -= stolen
            agent.resources += stolen

            # 可能获取知识
            if target.knowledge_base and random.random() < 0.5:
                k = random.choice(list(target.knowledge_base.values()))
                agent.adopt_knowledge(k)

    def _symbiot_action(self, agent: Agent):
        """共生者行为 - 合作共赢"""
        # 找到相似智能体合作
        partners = [
            a for a in self.agents.values()
            if a.id != agent.id and a.role == AgentRole.SYMBIOT
        ]

        if partners:
            partner = random.choice(partners)
            # 交换知识
            if agent.knowledge_base and partner.knowledge_base:
                k1 = random.choice(list(agent.knowledge_base.values()))
                k2 = random.choice(list(partner.knowledge_base.values()))

                agent.adopt_knowledge(k2)
                partner.adopt_knowledge(k1)

            # 共享收益
            shared = 10
            agent.resources += shared
            partner.resources += shared

    def _record_history(self):
        """记录历史"""
        role_counts = defaultdict(int)
        total_resources = 0
        total_knowledge = 0

        for agent in self.agents.values():
            role_counts[agent.role] += 1
            total_resources += agent.resources
            total_knowledge += len(agent.knowledge_base)

        self.history.append({
            'generation': self.generation,
            'population': len(self.agents),
            'role_distribution': dict(role_counts),
            'total_resources': total_resources,
            'avg_knowledge': total_knowledge / max(1, len(self.agents)),
            'best_agent': max(self.agents.values(), key=lambda a: a.resources).id if self.agents else None
        })

    def get_best_strategies(self, n: int = 5) -> List[Knowledge]:
        """获取最佳策略"""
        all_knowledge = []
        for agent in self.agents.values():
            all_knowledge.extend(agent.knowledge_base.values())

        return sorted(all_knowledge, key=lambda k: k.fitness, reverse=True)[:n]

    def get_society_stats(self) -> Dict:
        """获取社会统计"""
        if not self.agents:
            return {}

        return {
            'generation': self.generation,
            'population': len(self.agents),
            'avg_resources': np.mean([a.resources for a in self.agents.values()]),
            'avg_knowledge': np.mean([len(a.knowledge_base) for a in self.agents.values()]),
            'role_distribution': {
                role: sum(1 for a in self.agents.values() if a.role == role)
                for role in AgentRole
            }
        }

    def run_simulation(self, n_generations: int = 100):
        """运行模拟"""
        print(f"[Civilization] Starting simulation with {len(self.agents)} agents")

        for gen in range(n_generations):
            self.simulate_step()

            if gen % 20 == 0:
                stats = self.get_society_stats()
                print(f"Gen {gen}: pop={stats['population']}, "
                      f"avg_res={stats['avg_resources']:.1f}, "
                      f"avg_know={stats['avg_knowledge']:.1f}")

        print(f"[Civilization] Simulation complete after {n_generations} generations")


    def export_state(self) -> Dict:
        """Export civilization state to a JSON-serializable dict."""

        def _knowledge_to_dict(k: Knowledge) -> Dict:
            return {
                'id': k.id,
                'content': k.content,
                'creator': k.creator,
                'fitness': k.fitness,
                'age': k.age,
                'adoption_count': k.adoption_count,
            }

        def _agent_to_dict(a: Agent) -> Dict:
            return {
                'id': a.id,
                'role': a.role.value,
                'resources': a.resources,
                'reputation': a.reputation,
                'generation': a.generation,
                'parent_id': a.parent_id,
                'knowledge_base': {
                    k_id: _knowledge_to_dict(k) for k_id, k in a.knowledge_base.items()
                },
            }

        return {
            'n_agents': self.n_agents,
            'world_size': self.world_size,
            'resource_regen_rate': self.resource_regen_rate,
            'agents': {aid: _agent_to_dict(a) for aid, a in self.agents.items()},
            'global_knowledge': {
                k_id: _knowledge_to_dict(k) for k_id, k in self.global_knowledge.items()
            },
            'market_prices': dict(self.market_prices),
            'generation': self.generation,
            'history': list(self.history),
        }

    def import_state(self, state: Dict):
        """Restore civilization state from a dict."""
        self.n_agents = state.get('n_agents', self.n_agents)
        self.world_size = state.get('world_size', self.world_size)
        self.resource_regen_rate = state.get('resource_regen_rate', self.resource_regen_rate)
        self.generation = state.get('generation', 0)
        self.market_prices = defaultdict(float, state.get('market_prices', {}))

        # Restore history
        self.history = deque(maxlen=500)
        for entry in state.get('history', []):
            self.history.append(entry)

        # Helper to rebuild Knowledge
        def _dict_to_knowledge(data: Dict) -> Knowledge:
            return Knowledge(
                id=data['id'],
                content=data['content'],
                creator=data['creator'],
                fitness=data.get('fitness', 0.0),
                age=data.get('age', 0),
                adoption_count=data.get('adoption_count', 0),
            )

        # Restore global knowledge
        self.global_knowledge = {}
        for k_id, k_data in state.get('global_knowledge', {}).items():
            self.global_knowledge[k_id] = _dict_to_knowledge(k_data)

        # Restore agents
        self.agents = {}
        for aid, a_data in state.get('agents', {}).items():
            agent = Agent(
                id=a_data['id'],
                role=AgentRole(a_data['role']),
                resources=a_data.get('resources', 100.0),
                reputation=a_data.get('reputation', 1.0),
                generation=a_data.get('generation', 0),
                parent_id=a_data.get('parent_id'),
            )
            for k_id, k_data in a_data.get('knowledge_base', {}).items():
                agent.knowledge_base[k_id] = _dict_to_knowledge(k_data)
            self.agents[aid] = agent


if __name__ == "__main__":
    # 创建文明
    civ = AgentCivilization(n_agents=30)

    # 运行模拟
    civ.run_simulation(n_generations=100)

    # 查看最佳策略
    print("\n=== Top Strategies ===")
    for i, k in enumerate(civ.get_best_strategies(5)):
        print(f"{i+1}. {k.id}: fitness={k.fitness:.3f}, "
              f"creator={k.creator}, age={k.age}")

    # 查看角色分布
    stats = civ.get_society_stats()
    print(f"\n=== Final Role Distribution ===")
    for role, count in stats['role_distribution'].items():
        print(f"  {role.value}: {count}")
