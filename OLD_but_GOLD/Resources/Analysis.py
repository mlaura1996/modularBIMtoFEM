import openseespy.opensees as ops

pid = ops.getPID()

print(pid)
np = ops.getNP()
print(np)

print('HelloWorld', pid)
if pid == 0:
    print('Total num', np)

ops.model("basicBuilder","-ndm",3,"-ndf",3)

ops.uniaxialMaterial('Elastic', 1, 3000)