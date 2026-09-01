from backend.app.tools.system_tools import (
    get_system_info,
    get_cpu_usage,
    get_memory_usage,
    get_disk_usage,
    get_running_processes,
)


print("SYSTEM")
print(get_system_info())

print("\nCPU")
print(get_cpu_usage())

print("\nMEMORY")
print(get_memory_usage())

print("\nDISK")
print(get_disk_usage())

print("\nPROCESSES")
print(get_running_processes())