/** One tool the assistant can use, with questions that make it use that tool. */
export interface HelpTool {
  /** The tool's name as the assistant sees it. */
  readonly name: string;
  readonly description: string;
  readonly questions: readonly string[];
}

export interface HelpSection {
  readonly id: string;
  readonly title: string;
  readonly summary: string;
  /** Shown under the summary when the section needs something the user may not have. */
  readonly requirement?: string;
  readonly tools: readonly HelpTool[];
}

/**
 * The help page of Ask the Net: every tool group, what each tool does and questions that use it.
 * Keep it in step with the tool list in doc/AI_TOOL_CHAIN.md and `build_general_session`.
 */
export const HELP_SECTIONS: readonly HelpSection[] = [
  {
    id: "batfish",
    title: "Batfish (network model)",
    summary:
      "Answers come from a Batfish snapshot built from your backed-up device configurations. It is a model, not the live network. Every answer names the snapshot it used.",
    requirement: "Needs the permission to query Batfish.",
    tools: [
      {
        name: "list_batfish_networks / list_batfish_snapshots",
        description:
          "Lists the networks and their snapshots, newest first. Use it to see how old the data is or to pick another snapshot.",
        questions: [
          "How old is the data you are using?",
          "Which snapshots exist for this network?",
        ],
      },
      {
        name: "get_routes",
        description:
          "Routes of the model, with longest-prefix match for a single address.",
        questions: [
          "Which route does 10.1.2.3 use on r1?",
          "Show the static routes on r1.",
        ],
      },
      {
        name: "get_traceroute",
        description:
          "Simulates the path of a packet hop by hop, including where it is dropped and why.",
        questions: [
          "Where does a packet from r1 to 10.1.2.3 go?",
          "Why is traffic from r1 to 10.9.9.9 dropped?",
        ],
      },
      {
        name: "get_bgp_session_status",
        description: "BGP sessions with their status, optionally only the problems.",
        questions: [
          "Are all BGP sessions established?",
          "Which BGP sessions are not established?",
        ],
      },
      {
        name: "get_interface_properties",
        description:
          "Interface settings from the configs: address, VLAN, MTU, filters, active state, plus a summary.",
        questions: [
          "What are the interface settings of r1?",
          "Which interfaces on r1 are configured up but inactive?",
        ],
      },
      {
        name: "get_device_facts",
        description:
          "Facts from the configs: syslog, NTP, DNS, TACACS and SNMP trap servers, hostname, VRFs.",
        questions: [
          "Which devices have no NTP server configured?",
          "Which syslog servers does r1 use?",
        ],
      },
      {
        name: "list_snapshot_devices / get_ip_owners",
        description:
          "Lists the devices of a snapshot and which device and interface owns an IP address, including address conflicts.",
        questions: [
          "Which devices are in the snapshot?",
          "Who owns 10.1.2.3?",
          "Are there duplicate IP addresses in the snapshot?",
        ],
      },
      {
        name: "analyze_acl",
        description: "Tests one flow against one ACL or filter and shows permit or deny.",
        questions: [
          "Does the ACL EDGE-IN on r1 permit TCP 443 from 10.1.1.1 to 10.2.2.2?",
        ],
      },
      {
        name: "check_reachability",
        description:
          "Whether traffic can get from a device to a destination, with the paths found. Can ignore filters to separate a filter problem from a routing problem.",
        questions: [
          "Can r1 reach 10.2.2.2 over TCP port 22?",
          "Is the problem to 10.2.2.2 a filter or a routing problem?",
        ],
      },
      {
        name: "compare_filters / differential_reachability",
        description:
          "Compares two snapshots: ACL lines that treat a flow differently, and flows whose outcome differs.",
        questions: [
          "Which ACL lines changed between the last two snapshots?",
          "Which flows from r1 work in the old snapshot but not in the new one?",
        ],
      },
      {
        name: "get_snapshot_parse_issues",
        description:
          "What Batfish could not parse in the configs: failed or partly parsed files and unrecognised lines.",
        questions: [
          "Show me the parsing errors of the newest snapshot.",
          "Why are so many interfaces inactive?",
        ],
      },
      {
        name: "query_result / fetch_slice / diff_results",
        description:
          "Large results are stored behind a handle. These tools page through them, and compare two stored results.",
        questions: [
          "Show the next rows of that result.",
          "What changed between the routes of these two snapshots?",
        ],
      },
    ],
  },
  {
    id: "nautobot",
    title: "Nautobot (documented inventory)",
    summary:
      "Reads what is documented in Nautobot: devices, interfaces, locations, IP addresses and prefixes. It shows what is recorded, not how the network behaves.",
    requirement: "Needs the Nautobot read permission and a configured Nautobot source.",
    tools: [
      {
        name: "list_devices / get_device",
        description: "Searches devices by name, role, location, status, platform or tag, and shows one device.",
        questions: [
          "How many devices are in Nautobot?",
          "List the active switches in Berlin.",
          "Show the details of r1 in Nautobot.",
        ],
      },
      {
        name: "list_interfaces",
        description: "Interfaces of a device as documented in Nautobot.",
        questions: ["Which interfaces of r1 are documented in Nautobot?"],
      },
      {
        name: "list_ip_addresses / list_prefixes / list_namespaces",
        description: "IPAM reads: addresses, prefixes and namespaces.",
        questions: [
          "Who is 10.1.2.3 assigned to in Nautobot?",
          "Which prefixes are documented in location Berlin?",
        ],
      },
      {
        name: "get_next_free_ip",
        description: "Finds the next free addresses in a prefix. It only reads; nothing is reserved.",
        questions: ["What is the next free IP address in 10.1.2.0/24?"],
      },
      {
        name: "list_locations / get_location / list_location_types",
        description: "The location hierarchy and its types.",
        questions: ["Which locations exist below Germany?"],
      },
      {
        name: "list_roles / list_statuses / list_tags / list_device_types / list_platforms",
        description: "The vocabularies Nautobot uses, so a question can use the exact value.",
        questions: [
          "Which device roles exist?",
          "Which platforms are used in Nautobot?",
        ],
      },
      {
        name: "list_virtual_chassis / get_virtual_chassis",
        description: "Stacks and their member switches.",
        questions: [
          "Which virtual chassis exist, and how many members does each have?",
        ],
      },
      {
        name: "get_device_name_matches",
        description:
          "Finds a device under both names: the Batfish node name (config hostname) and the Nautobot full name.",
        questions: [
          "Which Nautobot device is the Batfish node lab?",
        ],
      },
    ],
  },
  {
    id: "config-backups",
    title: "Config backups (git)",
    summary:
      "Reads the backed-up running and startup configurations from the git repository. Instant, no SSH, but possibly older than the live device. Each answer says when the backup was committed.",
    requirement: "Needs the permission to read git files and the opt-in to share configuration content.",
    tools: [
      {
        name: "list_config_backups",
        description: "Lists the repositories that hold device configuration backups.",
        questions: ["Which config backup repositories exist?"],
      },
      {
        name: "get_config_backup",
        description: "Reads the running or startup configuration of one device.",
        questions: [
          "Show the running config of r1 from the backup.",
          "When was the config of r1 last backed up?",
        ],
      },
      {
        name: "search_config_backups",
        description:
          "Finds which devices contain a text or regular expression in their backed-up configuration.",
        questions: [
          "Which devices have snmp-server community public configured?",
          "Which devices have no ntp server line in their running config?",
        ],
      },
    ],
  },
  {
    id: "device-commands",
    title: "Live device commands",
    summary:
      "For the current state of a device. The assistant only proposes a read-only show command; nothing runs until you confirm it with a click.",
    requirement:
      "Switched on by the operator. Needs the command-execution permission and the opt-in to share content.",
    tools: [
      {
        name: "propose_device_command",
        description: "Proposes one read-only command for one device, which you confirm and run.",
        questions: [
          "Run show version on r1.",
          "What is the current uptime of r1?",
        ],
      },
    ],
  },
  {
    id: "runs",
    title: "Workflow runs",
    summary:
      "Explains runs you may see: what happened, which step failed and why, and what a step produced.",
    requirement: "Needs permission to read workflow runs.",
    tools: [
      {
        name: "list_runs / get_run",
        description: "Finds runs and shows the status of one run with its steps.",
        questions: [
          "Which runs failed today?",
          "Why did run 123 fail?",
        ],
      },
      {
        name: "get_step_result / get_artifact",
        description: "Reads the result of one step or an artifact the run produced.",
        questions: ["What did the backup step of run 123 return for r1?"],
      },
      {
        name: "list_run_events / get_run_workflow",
        description: "Live events inside a step and the workflow definition a run used.",
        questions: ["Show the events of run 123.", "Which workflow did run 123 use?"],
      },
    ],
  },
  {
    id: "workflows",
    title: "Released workflows",
    summary:
      "An administrator can release a workflow for Ask the Net. The assistant describes it and proposes a run; the run starts as you after you confirm.",
    requirement: "Needs permission to execute workflows. Only released workflows you may run are listed.",
    tools: [
      {
        name: "list_released_workflows / describe_workflow",
        description: "Lists the released workflows and describes what one does and what it needs.",
        questions: [
          "Which workflows can you start for me?",
          "What does the interface backup workflow do?",
        ],
      },
      {
        name: "propose_workflow_run / get_run_result",
        description: "Proposes a run with the inputs you give, then reads the designated result.",
        questions: [
          "Run the config backup workflow for r1.",
          "What was the result of the run I just started?",
        ],
      },
    ],
  },
  {
    id: "playbooks",
    title: "Playbooks",
    summary:
      "Step-by-step procedures for typical troubleshooting jobs, including the ones your organisation added.",
    tools: [
      {
        name: "list_playbooks / get_playbook",
        description: "Lists the playbooks and loads the one that fits the question.",
        questions: [
          "Which playbooks do you have?",
          "Follow a playbook to find out why 10.1.2.3 is not reachable from r1.",
        ],
      },
    ],
  },
];
