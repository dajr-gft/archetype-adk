"""The domain: rules, use cases and storage, with no dependency on ADK or on a model.

Everything the legacy system decided is decided here, in plain Python that a unit test
runs without a model. The agent layer (``tools.py``, ``prompt.py``, ``agent.py``) only
talks to the user and calls this package.
"""
