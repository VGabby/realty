class DeclutterError(Exception):
    pass


class PlanError(DeclutterError):
    pass


class ExecuteError(DeclutterError):
    pass


class VerifyError(DeclutterError):
    pass


class CapabilityError(DeclutterError):
    pass


class PlanNextError(DeclutterError):
    pass


class AgentError(DeclutterError):
    pass
