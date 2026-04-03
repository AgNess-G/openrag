# ── VPC ───────────────────────────────────────────────────────────────────────

resource "ibm_is_vpc" "vpc" {
  name                      = var.vpc_name
  resource_group            = data.ibm_resource_group.rg.id
  address_prefix_management = "auto"
}

resource "ibm_is_subnet" "subnet" {
  name                     = "${var.prefix}-subnet"
  vpc                      = ibm_is_vpc.vpc.id
  zone                     = var.zone
  total_ipv4_address_count = 256
  resource_group           = data.ibm_resource_group.rg.id
}

# ── Public gateway (outbound internet for workers pulling images) ─────────────

resource "ibm_is_public_gateway" "gateway" {
  name           = "${var.prefix}-gateway"
  vpc            = ibm_is_vpc.vpc.id
  zone           = var.zone
  resource_group = data.ibm_resource_group.rg.id
}

resource "ibm_is_subnet_public_gateway_attachment" "attachment" {
  subnet         = ibm_is_subnet.subnet.id
  public_gateway = ibm_is_public_gateway.gateway.id
}

# ── Security group ────────────────────────────────────────────────────────────

resource "ibm_is_security_group" "sg" {
  name           = "${var.prefix}-sg"
  vpc            = ibm_is_vpc.vpc.id
  resource_group = data.ibm_resource_group.rg.id
}

# Allow all outbound
resource "ibm_is_security_group_rule" "egress_all" {
  group     = ibm_is_security_group.sg.id
  direction = "outbound"
  remote    = "0.0.0.0/0"
}

# Allow inbound within VPC
resource "ibm_is_security_group_rule" "ingress_vpc" {
  group     = ibm_is_security_group.sg.id
  direction = "inbound"
  remote    = ibm_is_vpc.vpc.id
}

# Allow inbound HTTPS (frontend/backend)
resource "ibm_is_security_group_rule" "ingress_https" {
  group     = ibm_is_security_group.sg.id
  direction = "inbound"
  remote    = "0.0.0.0/0"
  tcp {
    port_min = 443
    port_max = 443
  }
}
