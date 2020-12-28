import ast
import copy
import sys
from collections import OrderedDict

import yaml


def getthread_dim(pos):
    if pos == 0:
        code = "threadx_dim"
    elif pos == 1:
        code = "thready_dim"
    elif pos == 2:
        code = "threadz_dim"
    else:
        raise Exception("Cannot handle more than triply nested loops")
    return code


def traverse(node, args={}, forvars=[], declared=[]):
    if node.__class__.__name__ == "For":
        forvars.append(traverse(node.target, args, [], declared))
        if len(forvars) == 1:
            thread_var = "threadx_dim"
        elif len(forvars) == 2:
            thread_var = "thready_dim"
        elif len(forvars) == 3:
            thread_var = "threadz_dim"
        else:
            raise Exception("Cannot handle more than triply nested loops")
        if len(node.iter.args) == 1:
            code = "if ({0} < {1}) {{\n".format(thread_var, traverse(node.iter.args[0]))
        elif len(node.iter.args) == 2:
            code = "if (({0} < {1}) && ({0} >= {2})) {{\n".format(
                thread_var, traverse(node.iter.args[1]), traverse(node.iter.args[0])
            )
        else:
            raise Exception("Unable to handle Python for loops with >2 args")
        for subnode in node.body:
            code += traverse(subnode, args, copy.copy(forvars), declared)
        code += "}\n"
    elif node.__class__.__name__ == "While":
        assert node.test.__class__.__name__ == "Compare"
        assert len(node.test.ops) == 1
        code = "while ({0}) {{\n".format(traverse(node.test))
        for subnode in node.body:
            code += traverse(subnode, args, copy.copy(forvars), declared)
        code += "}\n"
    elif node.__class__.__name__ == "Raise":
        if sys.version_info[0] == 2:
            code = 'err->str = "{0}";\n'.format(node.type.args[0].s)
        elif sys.version_info[0] == 3 and sys.version_info[1] in [5, 6, 7]:
            code = 'err->str = "{0}";\n'.format(node.exc.args[0].s)
        else:
            code = 'err->str = "{0}";\n'.format(node.exc.args[0].value)
        code += "err->filename = FILENAME(__LINE__);\nerr->pass_through=true;\n"
    elif node.__class__.__name__ == "If":
        code = ""
        code += "if ({0}) {{\n".format(
            traverse(node.test, args, copy.copy(forvars), declared)
        )
        tempdeclared = copy.copy(declared)
        for subnode in node.body:
            code += (
                " " * 2
                + traverse(subnode, args, copy.copy(forvars), tempdeclared)
                + "\n"
            )
        code += "} else {\n"
        for subnode in node.orelse:
            code += (
                " " * 2 + traverse(subnode, args, copy.copy(forvars), declared) + "\n"
            )
        code += "}\n"
    elif node.__class__.__name__ == "BoolOp":
        if node.op.__class__.__name__ == "Or":
            operator = "||"
        elif node.op.__class__.__name__ == "And":
            operator = "&&"
        assert len(node.values) == 2
        code = "{0} {1} {2}".format(
            traverse(node.values[0], args, copy.copy(forvars), declared),
            operator,
            traverse(node.values[1], args, copy.copy(forvars), declared),
        )
    elif node.__class__.__name__ == "Name":
        if node.id in forvars:
            code = getthread_dim(forvars.index(node.id))
        else:
            code = node.id
    elif node.__class__.__name__ == "NameConstant":
        if node.value == True:
            code = "true"
        elif node.value == False:
            code = "false"
        else:
            raise Exception("Unhandled NameConstant value {0}".format(node.value))
    elif node.__class__.__name__ == "Num":
        code = str(node.n)
    elif node.__class__.__name__ == "BinOp":
        left = traverse(node.left, args, copy.copy(forvars), declared)
        right = traverse(node.right, args, copy.copy(forvars), declared)
        if left in forvars:
            left = getthread_dim(forvars.index(left))
        if right in forvars:
            right = getthread_dim(forvars.index(right))
        code = "({0} {1} {2})".format(
            left,
            traverse(node.op, args, copy.copy(forvars), declared),
            right,
        )
    elif node.__class__.__name__ == "UnaryOp":
        if node.op.__class__.__name__ == "USub":
            code = "-{0}".format(
                traverse(node.operand, args, copy.copy(forvars), declared)
            )
        elif node.op.__class__.__name__ == "Not":
            code = "!{0}".format(
                traverse(node.operand, args, copy.copy(forvars), declared)
            )
        else:
            raise Exception(
                "Unhandled UnaryOp node {0}. Please inform the developers.".format(
                    node.op.__class__.__name__
                )
            )
    elif node.__class__.__name__ == "BitOr":
        code = "|"
    elif node.__class__.__name__ == "Sub":
        code = "-"
    elif node.__class__.__name__ == "Add":
        code = "+"
    elif node.__class__.__name__ == "Mult":
        code = "*"
    elif node.__class__.__name__ == "Subscript":
        if (
            node.slice.value.__class__.__name__ == "Name"
            and node.slice.value.id in forvars
        ):
            code = (
                node.value.id
                + "["
                + getthread_dim(forvars.index(node.slice.value.id))
                + "]"
            )
        elif (
            node.slice.value.__class__.__name__ == "Constant"
            or node.slice.value.__class__.__name__ == "BinOp"
            or node.slice.value.__class__.__name__ == "Subscript"
            or node.slice.value.__class__.__name__ == "Name"
            or node.slice.value.__class__.__name__ == "Num"
        ) and hasattr(node.value, "id"):
            code = (
                node.value.id
                + "["
                + traverse(node.slice.value, args, copy.copy(forvars), declared)
                + "]"
            )
        elif node.value.__class__.__name__ == "Subscript":
            code = (
                traverse(node.value.value)
                + "["
                + traverse(node.value.slice.value)
                + "]["
                + traverse(node.slice.value)
                + "]"
            )
        else:
            code = traverse(node.slice.value, args, copy.copy(forvars), declared)
    elif node.__class__.__name__ == "Call":
        assert len(node.args) == 1
        if node.func.id == "uint8":
            casttype = "uint8_t"
        else:
            casttype = node.func.id
        code = "({0})({1})".format(
            casttype, traverse(node.args[0], args, copy.copy(forvars), declared)
        )
    elif node.__class__.__name__ == "BitAnd":
        code = "&"
    elif node.__class__.__name__ == "Constant":
        if node.value == True:
            code = "true"
        elif node.value == False:
            code = "false"
        else:
            code = node.value
    elif node.__class__.__name__ == "Compare":
        if len(node.ops) == 1 and node.ops[0].__class__.__name__ == "Lt":
            code = "({0} < {1})".format(
                traverse(node.left, args, copy.copy(forvars), declared),
                traverse(node.comparators[0], args, copy.copy(forvars), declared),
            )
        elif len(node.ops) == 1 and node.ops[0].__class__.__name__ == "NotEq":
            code = "({0} != {1})".format(
                traverse(node.left, args, copy.copy(forvars), declared),
                traverse(node.comparators[0], args, copy.copy(forvars), declared),
            )
        elif len(node.ops) == 1 and node.ops[0].__class__.__name__ == "Eq":
            code = "({0} == {1})".format(
                traverse(node.left, args, copy.copy(forvars), declared),
                traverse(node.comparators[0], args, copy.copy(forvars), declared),
            )
        elif len(node.ops) == 1 and node.ops[0].__class__.__name__ == "Gt":
            code = "({0} > {1})".format(
                traverse(node.left, args, copy.copy(forvars), declared),
                traverse(node.comparators[0], args, copy.copy(forvars), declared),
            )
        elif len(node.ops) == 1 and node.ops[0].__class__.__name__ == "GtE":
            code = "({0} >= {1})".format(
                traverse(node.left, args, copy.copy(forvars), declared),
                traverse(node.comparators[0], args, copy.copy(forvars), declared),
            )
        elif len(node.ops) == 1 and node.ops[0].__class__.__name__ == "LtE":
            code = "({0} <= {1})".format(
                traverse(node.left, args, copy.copy(forvars), declared),
                traverse(node.comparators[0], args, copy.copy(forvars), declared),
            )
        else:
            raise Exception(
                "Unhandled Compare node {0}. Please inform the developers.".format(
                    node.ops[0]
                )
            )
    elif node.__class__.__name__ == "AugAssign" or node.__class__.__name__ == "Assign":
        if node.__class__.__name__ == "Assign":
            assert len(node.targets) == 1
            operator = "="
            targetnode = node.targets[0]
        else:
            if node.op.__class__.__name__ == "Add":
                operator = "+="
            elif node.op.__class__.__name__ == "RShift":
                operator = ">>="
            elif node.op.__class__.__name__ == "LShift":
                operator = "<<="
            else:
                raise Exception(
                    "Unhandled AugAssign node {0}".format(node.op.__class__.__name__)
                )
            targetnode = node.target
        left = traverse(targetnode, args, copy.copy(forvars), declared)
        if "[" in left:
            left = left[: left.find("[")]
        code = ""
        if left not in args.keys() and ("*" + left) not in args.keys():
            flag = True
        else:
            flag = False
        if node.value.__class__.__name__ == "Name" and (node.value.id in forvars):
            code = ""
            if flag and (
                traverse(targetnode, args, copy.copy(forvars), declared) not in declared
            ):
                code += "auto "
                declared.append(
                    traverse(targetnode, args, copy.copy(forvars), declared)
                )
            thread_var = getthread_dim(forvars.index(node.value.id))
            code += "{0} = {1};\n".format(
                traverse(targetnode, args, copy.copy(forvars), declared), thread_var
            )
        else:
            if node.value.__class__.__name__ == "IfExp":
                if flag and (
                    traverse(targetnode, args, copy.copy(forvars), declared)
                    not in declared
                ):
                    code = "auto {0} {1} {2};\n".format(
                        traverse(targetnode, args, copy.copy(forvars), declared),
                        operator,
                        traverse(node.value.orelse, args, copy.copy(forvars), declared),
                    )
                    declared.append(
                        traverse(targetnode, args, copy.copy(forvars), declared)
                    )
                code += "if ({0}) {{\n {1} {2} {3};\n }} else {{\n {1} {2} {4};\n }}\n".format(
                    traverse(node.value.test, args, copy.copy(forvars), declared),
                    traverse(targetnode, args, copy.copy(forvars), declared),
                    operator,
                    traverse(node.value.body, args, copy.copy(forvars), declared),
                    traverse(node.value.orelse, args, copy.copy(forvars), declared),
                )
            elif node.value.__class__.__name__ == "Compare":
                assert len(node.value.ops) == 1
                code = ""
                if flag and (
                    traverse(targetnode, args, copy.copy(forvars), declared)
                    not in declared
                ):
                    code += "auto "
                    declared.append(
                        traverse(targetnode, args, copy.copy(forvars), declared)
                    )
                if node.value.ops[0].__class__.__name__ == "Lt":
                    compop = "<"
                elif node.value.ops[0].__class__.__name__ == "Gt":
                    compop = ">"
                elif node.value.ops[0].__class__.__name__ == "LtE":
                    compop = "<="
                elif node.value.ops[0].__class__.__name__ == "GtE":
                    compop = ">="
                elif node.value.ops[0].__class__.__name__ == "NotEq":
                    compop = "!="
                elif node.value.ops[0].__class__.__name__ == "Eq":
                    compop = "=="
                else:
                    raise Exception(
                        "Unhandled Compare node {0}. Please inform the developers.".format(
                            node.value.ops[0]
                        )
                    )
                code += "{0} {1} {2} {3} {4};\n".format(
                    traverse(targetnode, args, copy.copy(forvars), declared),
                    operator,
                    traverse(node.value.left, args, copy.copy(forvars), declared),
                    compop,
                    traverse(
                        node.value.comparators[0],
                        args,
                        copy.copy(forvars),
                        declared,
                    ),
                )
            else:
                code = ""
                if flag and (
                    traverse(targetnode, args, copy.copy(forvars), declared)
                    not in declared
                ):
                    code += "auto "
                    declared.append(
                        traverse(targetnode, args, copy.copy(forvars), declared)
                    )
                code += "{0} {1} {2};\n".format(
                    traverse(targetnode, args, copy.copy(forvars), declared),
                    operator,
                    traverse(node.value, args, copy.copy(forvars), declared),
                )
    else:
        raise Exception("Unhandled node {0}".format(node.__class__.__name__))
    return code


def getbody(pycode, args):
    code = ""
    tree = ast.parse(pycode).body[0]
    declared = []
    for node in tree.body:
        code += traverse(node, args, [], declared)
    return code


def getxthreads(pycode):
    tree = ast.parse(pycode).body[0]
    forargs = set()
    flag = False
    while flag is False and "body" in dir(tree):
        for node in tree.body:
            if node.__class__.__name__ == "For":
                forargs.add(traverse(node.iter.args[0]))
                flag = True
            elif node.__class__.__name__ == "While":
                assert node.test.__class__.__name__ == "Compare"
                assert len(node.test.ops) == 1
                assert node.test.ops[0].__class__.__name__ == "Lt"
                assert len(node.test.comparators) == 1
                forargs.add(traverse(node.test.comparators[0]))
                flag = True
        tree = tree.body[0]
    if len(forargs) == 0:
        return 1
    elif len(forargs) == 1:
        return next(iter(forargs))
    else:
        lenarg = "std::max("
        count = 0
        for arg in forargs:
            if count == 0:
                lenarg += arg
                count += 1
            else:
                lenarg += ", " + arg
        lenarg += ")"
        return lenarg


def getythreads(pycode):
    tree = ast.parse(pycode).body[0]
    forargs = set()
    for node in tree.body:
        if node.__class__.__name__ == "For":
            for subnode in node.body:
                if subnode.__class__.__name__ == "For":
                    forargs.add(traverse(node.iter.args[0]))
    assert len(forargs) == 0 or len(forargs) == 1
    if len(forargs) == 0:
        return "1"
    elif len(forargs) == 1:
        return next(iter(forargs))
    else:
        raise Exception("Only doubly nested for loops can be handled")


def getctype(typename):
    pointercount = 0
    if "Const[" in typename:
        typename = typename[:-1]
        typename = typename.replace("Const[", "", 1)
        cpptype = "const "
    else:
        cpptype = ""
    while "List[" in typename:
        typename = typename[5:]
        typename = typename[:-1]
        pointercount += 1
    cpptype += typename + "*" * pointercount
    return cpptype


def gettemplateargs(spec):
    templateargs = OrderedDict()
    typelist = []
    templascii = 65
    for arg in spec["specializations"][0]["args"]:
        typelist.append(arg["type"])
    for i in range(len(spec["specializations"][0]["args"])):
        for childfunc in spec["specializations"]:
            if (
                typelist[i] != childfunc["args"][i]["type"]
                and childfunc["args"][i]["name"] not in templateargs.keys()
            ):
                templateargs[childfunc["args"][i]["name"]] = chr(templascii)
                templascii += 1
    return templateargs


def getparentargs(templateargs, spec):
    args = OrderedDict()
    for arg in spec["specializations"][0]["args"]:
        argname = arg["name"]
        if arg["name"] in templateargs.keys():
            if "*" in getctype(arg["type"]):
                argname = "*" + argname
            if "Const[" in arg["type"]:
                args[argname] = "const " + templateargs[arg["name"]]
            else:
                args[argname] = templateargs[arg["name"]]
        else:
            args[argname] = getctype(arg["type"])
    return args


def getchildargs(childfunc, spec):
    args = OrderedDict()
    for arg in childfunc["args"]:
        args[arg["name"]] = getctype(arg["type"])
    return args


def gettemplatestring(templateargs):
    count = 0
    templatestring = ""
    for x in templateargs.values():
        if count == 0:
            templatestring += "typename " + x
            count += 1
        else:
            templatestring += ", typename " + x
    return templatestring


def getdecl(name, args, templatestring, parent=False, ret="void"):
    code = ""
    if templatestring != "":
        code += "template <" + templatestring + ">\n"
    if parent:
        code += "__global__\n"
    count = 0
    for key, value in args.items():
        if count == 0:
            params = value + " " + key
            count += 1
        else:
            params += ", " + value + " " + key
    if parent:
        code += "void cuda" + name + "(" + params + ") {\n"
    else:
        code += ret + " " + name + "(" + params + ") {\n"
    return code


def gettemplatetypes(spec, templateargs):
    count = 0
    code = ""
    for arg in spec["args"]:
        for argname, info in arg.items():
            if argname in templateargs.keys():
                if count == 0:
                    code += getctype(info["type"]).replace("*", "")
                    count += 1
                else:
                    code += ", " + getctype(info["type"]).replace("*", "")
    if "const " in code:
        code = code.replace("const ", "")
    return code


def getparamnames(args):
    count = 0
    for arg in args.keys():
        if count == 0:
            code = arg
            count += 1
        else:
            code += ", " + arg
    return code


def getcode(indspec):
    templateargs = gettemplateargs(indspec)
    args = getparentargs(templateargs, indspec)
    templatestring = gettemplatestring(templateargs)
    code = getdecl(indspec["name"], args, templatestring, True, indspec["ret"])
    code += """  int64_t threadx_dim = blockIdx.x * blockDim.x + threadIdx.x;
int64_t thready_dim = blockIdx.y * blockDim.y + threadIdx.y;
"""
    code += getbody(indspec["definition"], args)
    code += "}\n\n"
    for childfunc in indspec["specializations"]:
        args = getchildargs(childfunc, indspec)
        code += getdecl(childfunc["name"], args, "")
        code += """  dim3 blocks_per_grid;
dim3 threads_per_block;

if ({0} > 1024 && {1} > 1024) {{
blocks_per_grid = dim3(ceil({0} / 1024.0), ceil({1}/1024.0), 1);
threads_per_block = dim3(1024, 1024, 1);
}} else if ({0} > 1024) {{
blocks_per_grid = dim3(ceil({0} / 1024.0), 1, 1);
threads_per_block = dim3(1024, {1}, 1);
}} else if ({1} > 1024) {{
blocks_per_grid = dim3(1, ceil({1}/1024.0), 1);
threads_per_block = dim3({0}, 1024, 1);
}} else {{
blocks_per_grid = dim3(1, 1, 1);
threads_per_block = dim3({0}, {1}, 1);
}}""".format(
            getxthreads(indspec["definition"]), getythreads(indspec["definition"])
        )
        templatetypes = gettemplatetypes(childfunc, templateargs)
        paramnames = getparamnames(args)
        code += " " * 2 + "cuda" + indspec["name"]
        if templatetypes is not None and len(templatetypes) > 0:
            code += "<" + templatetypes + ">"
        code += " <<<blocks_per_grid, threads_per_block>>>(" + paramnames + ");\n"
        code += " " * 2 + "cudaDeviceSynchronize();\n"
        code += "}\n\n"
    return code


if __name__ == "__main__":
    code = """#include <algorithm>
#include <cstdio>

"""
    assert len(sys.argv) == 2
    filename = sys.argv[1]
    assert filename.endswith(".yml") or filename.endswith(".yaml")
    with open(filename, "r") as specfile:
        spec = yaml.safe_load(specfile)
        code += getcode(spec)
        print(code)
