from DatabaseAgent.AgentKernelFcatory import AgentKernelFactory

kernel = AgentKernelFactory.configure_kernel(
    None,
    logger_factory=None,
)

print(kernel.get_service(service_id="agent"))