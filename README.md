# QueryReformulatorTool
Master Thesis at Technical University Munich on LLM Agent-driven Tool Selection and Query Reformulator

# Abstract
Although Large Language Models (LLMs) have demonstrated impressive capabilities for information seeking scenarios through their vast inherent knowledge and strong reasoning ability, they struggle to deal with queries that require real-time knowledge of events or specialist knowledge, often resulting in them generating misleading or false information, often termed ‘hallucinations’.

To compensate for this limitation, recent research has explored integration of external tools and APIs, to augment the capabilities of LLMs in dealing with these real-time information seeking scenarios, in a typical Retrieval-augmented Generation (RAG) framework. While enhancing their problem solving capabilities, they also provide interpretability and foster user trust. Despite these advancements, they still struggle on multi-step queries.

In this thesis, we investigate the utility of incorporating components such as Query Decomposition (breaking a complex query into a sequence of steps), Query Reformulation (rewriting the query to make it more concise and targeted during reflection) and Self-refine (providing feedback to iterate over an incorrect answer), through an autonomous multi- agent system framework, to assist the model in more precise retrieval and accurate generations in RAG framework.

We validate our proposed method against an existing framework called AnyTool which uses function calling and a hierarchical agent-based retrieval system to solve queries requiring tool use. We observe clear positive results that demonstrate an effectiveness of our proposed additions, especially in solving multi-part queries that require 2 or more external tools.
