# Vendored from lightparam (https://github.com/portugueslab/lightparam),
# MIT License, Copyright (c) 2018 Portugues lab.
def pretty_name(paramname: str):
    pn = paramname.capitalize()
    pn = pn.replace("_", " ")
    return pn
