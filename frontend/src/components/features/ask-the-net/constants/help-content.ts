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
        description:
          "Searches devices by name, role, location, status, platform or tag, and shows one device. The interfaces of a device also show their documented cable and the device and interface at the other end.",
        questions: [
          "How many devices are in Nautobot?",
          "List the active switches in Berlin.",
          "Show the details of r1 in Nautobot.",
        ],
      },
      {
        name: "list_interfaces",
        description:
          "Interfaces of a device as documented in Nautobot, page by page. An interface with a documented cable also shows the device and interface at the other end of the cable, so this is how the assistant finds the neighbours of a device. Interfaces without a cable show no cable data; that means no cable is documented, not that nothing is plugged in. Cable labels need the content opt-in.",
        questions: [
          "Which interfaces of r1 are documented in Nautobot?",
          "Which devices are connected to r1 according to Nautobot?",
          "Show only the cabled interfaces of r1.",
        ],
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
    id: "catalyst-center",
    title: "Cisco Catalyst Center (controller)",
    summary:
      "Looks a device up in Cisco Catalyst Center and reads its facts. For a question about one device the assistant looks at Nautobot first, then checks Catalyst Center with the name, or with the IP address or serial number Nautobot shows. A device Catalyst Center does not know is reported as documented in Nautobot but not managed there. The data is the controller's last collected view, not a live command.",
    requirement:
      "Needs permission to read Catalyst Center sources. If no Catalyst Center source is configured, the assistant tells you an administrator must add one. Addresses and serial numbers need the addresses opt-in, interface descriptions the content opt-in.",
    tools: [
      {
        name: "find_catalyst_center_device",
        description:
          "Finds a device in Catalyst Center by name, management IP address or serial number and says whether the controller manages it.",
        questions: [
          "Is LAB managed by Catalyst Center?",
          "Which Catalyst Center device has the serial number FOC1234ABCD?",
        ],
      },
      {
        name: "get_catalyst_center_device_details",
        description:
          "Reads facts of one device from Catalyst Center: device record, software version, interfaces, VLANs and compliance. Device and software are the default.",
        questions: [
          "Show the Catalyst Center device details of LAB.",
          "Which software version does LAB run according to Catalyst Center?",
          "Show the interfaces and compliance status of LAB in Catalyst Center.",
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
        description:
          "Proposes read-only commands for one device, which you confirm and run. Ask for the output to be parsed (TextFSM, or Genie when it is available) and the result is shown as a table, with the raw output kept below it.",
        questions: [
          "Run show version on r1.",
          "What is the current uptime of r1?",
          "Run show ip interface brief on r1 and parse it with TextFSM.",
        ],
      },
      {
        name: "parse_command_output",
        description:
          "Parses the output of a command you already ran, without touching the device again. Genie only works if you approved Genie when you confirmed the command.",
        questions: ["Parse that output with TextFSM."],
      },
    ],
  },
  {
    id: "neighbors",
    title: "Neighbours (layer 2 and layer 3)",
    summary:
      "Which devices are attached to a device (CDP/LLDP) and which routers it exchanges routes with. Live results come from read-only commands that you confirm: the assistant picks them from a reviewed list and never writes them. For layer 3 it asks which routing protocol and VRF to look at, unless you said. The sources can differ: the live device is current, the model is as old as its snapshot, and Nautobot is documentation that may be incomplete. Missing in a source means no data, not not connected.",
    requirement:
      "Live discovery is switched on by the operator and needs the command-execution permission and the opt-in to share content. The model view needs the permission to query Batfish. The comparison with Nautobot also needs the Nautobot read permission and the addresses opt-in. Supported: Cisco IOS and IOS-XE, NX-OS, IOS-XR, Arista EOS and Junos.",
    tools: [
      {
        name: "propose_neighbor_discovery",
        description:
          "Proposes the neighbour commands for one device, which you confirm and run: CDP and LLDP neighbours (layer 2), the routing table next hops, or the adjacencies of one routing protocol (OSPF, BGP, EIGRP, IS-IS) in a VRF. It can also list the routing protocols and VRFs a device uses, so you can choose.",
        questions: [
          "Which devices are connected to r1 according to CDP and LLDP?",
          "Which routing protocols and VRFs does r1 use?",
          "Which OSPF neighbours does r1 have?",
          "Show the next hops in the routing table of r1.",
        ],
      },
      {
        name: "get_discovery_result",
        description:
          "Reads the result of a discovery you confirmed and shows the neighbours as a table: interface, neighbour, address, platform or state. It checks each neighbour against the inventory and can compare the layer 2 neighbours with the cabling documented in Nautobot, listing what is confirmed, undocumented, missing on the device or in conflict.",
        questions: [
          "Compare the live neighbours of r1 with the cabling in Nautobot.",
          "Which neighbours of r1 are not in the inventory?",
        ],
      },
      {
        name: "get_modelled_neighbors",
        description:
          "Layer 3 and routing protocol neighbours as the Batfish model sees them, without touching the device. Not live, and it has no layer 2 information.",
        questions: [
          "Which OSPF neighbours does r1 have in the model?",
          "Which routers is r1 connected to at layer 3 in the newest snapshot?",
        ],
      },
      {
        name: "get_neighbor_sources",
        description:
          "Shows which evidence exists for a device (live discovery, the model, Nautobot cabling) and what its platform supports.",
        questions: ["What can you tell me about the neighbours of r1, and from which sources?"],
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
