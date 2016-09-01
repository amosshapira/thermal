import templates.vpc


def run(config, template):
    templates.vpc.configure_vpc(config, template)
