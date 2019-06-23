# URLs denoting Syndicate servers.

class InvalidSyndicateUrl(ValueError): pass

schemas = {}

def schema(schema_name):
    def k(factory_class):
        schemas[schema_name] = factory_class
        return factory_class
    return k

def _bad_url(u):
    raise InvalidSyndicateUrl('Invalid Syndicate server URL', u)

def connection_from_url(u):
    pieces = u.split(':', 1)
    if len(pieces) != 2: _bad_url(u)
    schema_name, _rest = pieces
    if schema_name not in schemas: _bad_url(u)
    conn = schemas[schema_name].from_url(u)
    if not conn: _bad_url(u)
    return conn

def _hostport(s, default_port):
    try:
        i = s.rindex(':')
    except ValueError:
        i = None
    if i is not None:
        return (s[:i], int(s[i+1:]))
    else:
        return (s, default_port)
