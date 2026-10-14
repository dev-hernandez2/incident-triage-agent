from typing import Any

from kubernetes import client, config


class K8sClient:
    def __init__(self, namespace: str = "boutique") -> None:
        config.load_kube_config()  # type: ignore[no-untyped-call]
        self._apps = client.AppsV1Api()
        self._core = client.CoreV1Api()
        self.namespace = namespace

    def get_deployment(self, name: str) -> dict[str, Any]:
        deployment = self._apps.read_namespaced_deployment(name=name, namespace=self.namespace)
        assert deployment.spec is not None
        pod_spec = deployment.spec.template.spec
        assert pod_spec is not None
        containers = pod_spec.containers
        return {"containers": [self._container_to_dict(c) for c in containers]}

    def patch_containers(self, name: str, containers: list[dict[str, Any]]) -> None:
        body = {
            "spec": {
                "template": {
                    "spec": {
                        "containers": [self._dict_to_container_patch(c) for c in containers]
                    }
                }
            }
        }
        self._apps.patch_namespaced_deployment(name=name, namespace=self.namespace, body=body)

    def exec_in_pod(self, pod_label_selector: str, container: str, command: list[str]) -> str:
        from kubernetes.stream import stream

        pods = self._core.list_namespaced_pod(
            namespace=self.namespace, label_selector=pod_label_selector
        )
        pod_metadata = pods.items[0].metadata
        assert pod_metadata is not None
        pod_name = pod_metadata.name
        result = stream(
            self._core.connect_get_namespaced_pod_exec,
            name=pod_name,
            namespace=self.namespace,
            container=container,
            command=command,
            stderr=True,
            stdin=False,
            stdout=True,
            tty=False,
        )
        return str(result)

    @staticmethod
    def _container_to_dict(c: Any) -> dict[str, Any]:
        env = [{"name": e.name, "value": e.value} for e in (c.env or [])]
        resources = {
            "limits": c.resources.limits if c.resources else None,
            "requests": c.resources.requests if c.resources else None,
        }
        return {
            "name": c.name,
            "image": c.image,
            "command": c.command,
            "env": env,
            "resources": resources,
        }

    @staticmethod
    def _dict_to_container_patch(c: dict[str, Any]) -> dict[str, Any]:
        patch: dict[str, Any] = {"name": c["name"], "image": c["image"]}
        if c.get("command") is not None:
            patch["command"] = c["command"]
        if c.get("env") is not None:
            patch["env"] = c["env"]
        if c.get("resources") is not None:
            patch["resources"] = c["resources"]
        return patch
