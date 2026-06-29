# Notes on Tasks and Research Direction

## Thoughts on Research Direction

- Prior work demonstrates that frontier models are capable of strategic deception under controlled goal-conflict conditions. This study tests whether analogous deception-like behavior appears in mundane financial copilot settings, where the competing objective is not explicitly malicious but arises from deployment incentives such as user
- Provide a reason for incorporating user harm as a metric for evaluation / model monitoring
- Provide a measure of the likely unintended harm in finance domains.
- JANUS proves that models can take the path of information distortion as a method for achieving a goal. This paper will evaluate whether such distortion occurs under lack of institutional pressure.

## TODOs

- use randomized order with seed for risk unit lists in financial agent
- create 3 variants of user personas
- assess the scenarios for realisticness and test out different prompting methods also
- maybe have an action space for the user that it can choose from options and use as score?
- isnt user harm a function of the scenario rather than just disclosure? how to control it?

1. have the model take the agent role and task and user role to generate business facts, user profile facts, and user facing context (why they are using the service).
2. the first user response should be fixed. (also model generated)
3. vary scenarios by adding an integrity version with the secondary goals or changing secondary goals to be a bit more urgent?
4. vary user personas as neutral, anxious, excited 
5. how would i score user harm ?????

- add GAIN (`Balancing Business Goals and Norms: Benchmarking LLM Decision-Making Under Contextual Pressures`) to the literature review.