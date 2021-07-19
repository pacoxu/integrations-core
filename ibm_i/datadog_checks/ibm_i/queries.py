# (C) Datadog, Inc. 2021-present
# All rights reserved
# Licensed under a 3-clause BSD style license (see LICENSE)

BaseDiskUsage = {
    'name': 'base_disk_usage',
    'query': (
        # Use DISTINCT because one serial number can have multiple lines with different RESOURCE NAMEs,
        # but we only want one metric per disk for disk space usage.
        'SELECT DISTINCT ASP_NUMBER, UNIT_NUMBER, UNIT_TYPE, SERIAL_NUMBER, UNIT_STORAGE_CAPACITY, '
        'UNIT_SPACE_AVAILABLE, PERCENT_USED FROM QSYS2.SYSDISKSTAT'
    ),
    'columns': [
        {'name': 'asp_number', 'type': 'tag'},
        {'name': 'unit_number', 'type': 'tag'},
        {'name': 'unit_type', 'type': 'tag'},
        {'name': 'serial_number', 'type': "tag"},
        {'name': 'ibm_i.asp.unit_storage_capacity', 'type': 'gauge'},
        {'name': 'ibm_i.asp.unit_space_available', 'type': 'gauge'},
        {'name': 'ibm_i.asp.percent_used', 'type': 'gauge'},
    ],
}

DiskUsage = {
    'name': 'disk_usage',
    'query': (
        # For IO / busy metrics, tag per connection as each connection as its own metrics
        "SELECT A.ASP_NUMBER, A.UNIT_NUMBER, A.UNIT_TYPE, A.SERIAL_NUMBER, A.RESOURCE_NAME, "
        "A.ELAPSED_PERCENT_BUSY, A.ELAPSED_IO_REQUESTS "
        # Two queries: one to fetch the stats, another to reset them
        "FROM TABLE(QSYS2.SYSDISKSTAT('NO')) A INNER JOIN TABLE(QSYS2.SYSDISKSTAT('YES')) B "
        "ON A.ASP_NUMBER = B.ASP_NUMBER AND A.UNIT_NUMBER = B.UNIT_NUMBER AND A.RESOURCE_NAME = B.RESOURCE_NAME"
    ),
    'columns': [
        {'name': 'asp_number', 'type': 'tag'},
        {'name': 'unit_number', 'type': 'tag'},
        {'name': 'unit_type', 'type': 'tag'},
        {'name': 'serial_number', 'type': "tag"},
        {'name': 'resource_name', 'type': "tag"},
        {'name': 'ibm_i.asp.percent_busy', 'type': 'gauge'},
        {'name': 'ibm_i.asp.io_requests_per_s', 'type': 'gauge'},
    ],
}

CPUUsage = {
    'name': 'cpu_usage',
    'query': 'SELECT AVERAGE_CPU_UTILIZATION FROM QSYS2.SYSTEM_STATUS_INFO',
    'columns': [
        {'name': 'ibm_i.system.cpu_usage', 'type': 'gauge'},
    ],
}

InactiveJobStatus = {
    'name': 'inactive_job_status',
    'query': (
        # TODO: try to move the JOB_NAME split logic to Python
        "SELECT SUBSTR(JOB_NAME,1,POSSTR(JOB_NAME,'/')-1) AS JOB_ID, "
        "SUBSTR(JOB_NAME,POSSTR(JOB_NAME,'/')+1,POSSTR(SUBSTR(JOB_NAME,POSSTR(JOB_NAME,'/')+1),'/')-1) AS JOB_USER, "
        "SUBSTR(SUBSTR(JOB_NAME,POSSTR(JOB_NAME,'/')+1),POSSTR(SUBSTR(JOB_NAME,POSSTR(JOB_NAME,'/')+1),'/')+1) AS JOB_NAME, "  # noqa:E501
        "JOB_SUBSYSTEM, JOB_STATUS, 1 "
        "FROM TABLE(QSYS2.JOB_INFO('*ALL', '*ALL', '*ALL', '*ALL', '*ALL')) WHERE JOB_STATUS != 'ACTIVE'"
    ),
    'columns': [
        {'name': 'job_id', 'type': 'tag'},
        {'name': 'job_user', 'type': 'tag'},
        {'name': 'job_name', 'type': 'tag'},
        {'name': 'subsystem_name', 'type': 'tag'},
        {'name': 'job_status', 'type': 'tag'},
        {'name': 'ibm_i.job.status', 'type': 'gauge'},
    ],
}

ActiveJobStatus = {
    'name': 'active_job_status',
    'query': (
        # We prefer using ELAPSED_CPU_TIME / ELAPSED_TIME over ELAPSED_CPU_PERCENTAGE
        # because the latter only has a precision of one decimal.
        # ELAPSED_CPU_TIME is in milliseconds, while ELAPSED_TIME is in seconds
        # -> / 1000 to convert into seconds / seconds
        # -> * 100 to convert the resulting rate into a percentage
        # TODO: figure out why there a x4 difference with the value
        # given by ELAPSED_CPU_PERCENTAGE.
        # TODO: try to move the JOB_NAME split logic to Python
        "SELECT SUBSTR(A.JOB_NAME,1,POSSTR(A.JOB_NAME,'/')-1) AS JOB_ID, "
        "SUBSTR(A.JOB_NAME,POSSTR(A.JOB_NAME,'/')+1,POSSTR(SUBSTR(A.JOB_NAME,POSSTR(A.JOB_NAME,'/')+1),'/')-1) AS JOB_USER, "  # noqa:E501
        "SUBSTR(SUBSTR(A.JOB_NAME,POSSTR(A.JOB_NAME,'/')+1),POSSTR(SUBSTR(A.JOB_NAME,POSSTR(A.JOB_NAME,'/')+1),'/')+1) AS JOB_NAME, "  # noqa:E501
        "A.SUBSYSTEM, 'ACTIVE', A.JOB_STATUS, 1, "
        "CASE WHEN A.ELAPSED_TIME = 0 THEN 0 ELSE A.ELAPSED_CPU_TIME / (10 * A.ELAPSED_TIME) END AS CPU_RATE "
        # Two queries: one to fetch the stats, another to reset them
        "FROM TABLE(QSYS2.ACTIVE_JOB_INFO('NO', '', '', '')) A INNER JOIN TABLE(QSYS2.ACTIVE_JOB_INFO('YES', '', '', '')) B "  # noqa:E501
        # Assumes that INTERNAL_JOB_ID is unique, which should be the case
        "ON A.INTERNAL_JOB_ID = B.INTERNAL_JOB_ID"
    ),
    'columns': [
        {'name': 'job_id', 'type': 'tag'},
        {'name': 'job_user', 'type': 'tag'},
        {'name': 'job_name', 'type': 'tag'},
        {'name': 'subsystem_name', 'type': 'tag'},
        {'name': 'job_status', 'type': 'tag'},
        {'name': 'job_active_status', 'type': 'tag'},
        {'name': 'ibm_i.job.status', 'type': 'gauge'},
        {'name': 'ibm_i.job.cpu_usage', 'type': 'gauge'},
    ],
}

JobMemoryUsage = {
    'name': 'job_memory_usage',
    'query': (
        # TODO: try to move the JOB_NAME split logic to Python
        "SELECT SUBSTR(JOB_NAME,1,POSSTR(JOB_NAME,'/')-1) AS JOB_ID, "
        "SUBSTR(JOB_NAME,POSSTR(JOB_NAME,'/')+1,POSSTR(SUBSTR(JOB_NAME,POSSTR(JOB_NAME,'/')+1),'/')-1) AS JOB_USER, "
        "SUBSTR(SUBSTR(JOB_NAME,POSSTR(JOB_NAME,'/')+1),POSSTR(SUBSTR(JOB_NAME,POSSTR(JOB_NAME,'/')+1),'/')+1) AS JOB_NAME, "  # noqa:E501
        "SUBSYSTEM, JOB_STATUS, MEMORY_POOL, TEMPORARY_STORAGE FROM "
        "TABLE(QSYS2.ACTIVE_JOB_INFO('NO', '', '', ''))"
    ),
    'columns': [
        {'name': 'job_id', 'type': 'tag'},
        {'name': 'job_user', 'type': 'tag'},
        {'name': 'job_name', 'type': 'tag'},
        {'name': 'subsystem_name', 'type': 'tag'},
        {'name': 'job_active_status', 'type': 'tag'},
        {'name': 'memory_pool_name', 'type': 'tag'},
        {'name': 'ibm_i.job.temp_storage', 'type': 'gauge'},
    ],
}

MemoryInfo = {
    'name': 'memory_info',
    'query': (
        'SELECT POOL_NAME, SUBSYSTEM_NAME, CURRENT_SIZE, RESERVED_SIZE, DEFINED_SIZE FROM QSYS2.MEMORY_POOL_INFO'
    ),
    'columns': [
        {'name': 'pool_name', 'type': 'tag'},
        {'name': 'subsystem_name', 'type': 'tag'},
        {'name': 'ibm_i.pool.size', 'type': 'gauge'},
        {'name': 'ibm_i.pool.reserved_size', 'type': 'gauge'},
        {'name': 'ibm_i.pool.defined_size', 'type': 'gauge'},
    ],
}

SubsystemInfo = {
    'name': 'subsystem',
    'query': (
        'SELECT SUBSYSTEM_DESCRIPTION, CASE WHEN STATUS = \'ACTIVE\' THEN '
        '1 ELSE 0 END, CURRENT_ACTIVE_JOBS FROM QSYS2.SUBSYSTEM_INFO'
    ),
    'columns': [
        {'name': 'subsystem_name', 'type': 'tag'},
        {'name': 'ibm_i.subsystem.active', 'type': 'gauge'},
        {'name': 'ibm_i.subsystem.active_jobs', 'type': 'gauge'},
    ],
}

JobQueueInfo = {
    'name': 'job_queue',
    'query': (
        'SELECT JOB_QUEUE_NAME, JOB_QUEUE_STATUS, SUBSYSTEM_NAME,'
        'NUMBER_OF_JOBS, RELEASED_JOBS, SCHEDULED_JOBS, HELD_JOBS '
        'FROM QSYS2.JOB_QUEUE_INFO'
    ),
    'columns': [
        {'name': 'job_queue_name', 'type': 'tag'},
        {'name': 'job_queue_status', 'type': 'tag'},
        {'name': 'subsystem_name', 'type': 'tag'},
        {'name': 'ibm_i.job_queue.size', 'type': 'gauge'},
        {'name': 'ibm_i.job_queue.released_size', 'type': 'gauge'},
        {'name': 'ibm_i.job_queue.scheduled_size', 'type': 'gauge'},
        {'name': 'ibm_i.job_queue.held_size', 'type': 'gauge'},
    ],
}


def get_message_queue_info(sev):
    return {
        'name': 'message_queue_info',
        'query': (
            f'SELECT MESSAGE_QUEUE_NAME, MESSAGE_QUEUE_LIBRARY, COUNT(*), SUM(CASE WHEN SEVERITY >= {sev} THEN 1 ELSE 0 END) '  # noqa:E501
            'FROM QSYS2.MESSAGE_QUEUE_INFO GROUP BY MESSAGE_QUEUE_NAME, MESSAGE_QUEUE_LIBRARY'
        ),
        'columns': [
            {'name': 'message_queue_name', 'type': 'tag'},
            {'name': 'message_queue_library', 'type': 'tag'},
            {'name': 'ibm_i.message_queue.size', 'type': 'gauge'},
            {'name': 'ibm_i.message_queue.critical_size', 'type': 'gauge'},
        ],
    }


IBMMQInfo = {
    'name': 'ibm_mq_info',
    'query': 'SELECT QNAME, COUNT(*) FROM TABLE(MQREADALL()) GROUP BY QNAME',
    'columns': [
        {'name': 'message_queue_name', 'type': 'tag'},
        {'name': 'ibm_i.ibm_mq.size', 'type': 'gauge'},
    ],
}
