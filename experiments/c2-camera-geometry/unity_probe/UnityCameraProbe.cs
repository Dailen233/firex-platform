// UnityCameraProbe.cs — C2 相机几何交叉验证探针（层级 3）
//
// 用途：用真实 Unity 引擎输出做第三层交叉验证。挂到任意 GameObject，指定 targetCamera，
// 在 Inspector 里填 worldPoints。运行后写 JSON 到 Application.persistentDataPath/camera_probe.json。
//
// 记录（用于确认 Python 的全屏透视假设是否适用）：
//   - Application.unityVersion（Unity 版本）
//   - Screen.width/height
//   - 相机 pixelWidth/pixelHeight、pixelRect、aspect、投影类型（perspective/orthographic）、
//     usePhysicalProperties（物理相机）
//   - localToWorldMatrix（row-major：data[r*4+c] = M[r][c]，与 TakePhoto.cs 一致）
//   - WorldToScreenPoint / ScreenPointToRay 结果
//
// 序列化：用 JsonUtility.ToJson（结构化序列化），不手工拼接浮点数，避免地区小数格式影响。
//
// 比较注意（两个关键点）：
// 1. WorldToScreenPoint 的像素 y 原点在左下，与 PNG 左上相反；用「连续坐标」翻转
//    v_image = H - y_screen（不是离散行号翻转 H-1-y）。
// 2. ScreenPointToRay.origin 位于近裁剪面（非光心）；比较「方向」或把 origin 沿 direction
//    平移到同一深度，再比较所在直线，不要直接比较原点。
using System.Collections.Generic;
using UnityEngine;

[System.Serializable]
public class ProbeVec3
{
    public float x, y, z;
    public ProbeVec3(Vector3 v) { x = v.x; y = v.y; z = v.z; }
}

[System.Serializable]
public class ProbeW2S
{
    public float[] world = new float[3];
    public float[] screen = new float[3];
}

[System.Serializable]
public class ProbeRay
{
    public float[] pixel = new float[2];
    public float[] origin = new float[3];
    public float[] direction = new float[3];
}

[System.Serializable]
public class CameraProbeReport
{
    public string unity_version;
    public int screen_width, screen_height;
    public float fov_y_deg;
    public int pixel_width, pixel_height;
    public float[] pixel_rect = new float[4]; // x, y, width, height
    public float aspect;
    public string projection_type;             // "perspective" | "orthographic"
    public bool use_physical_properties;
    public ProbeVec3 camera_position, camera_forward, camera_up, camera_right;
    public float[] camera_to_world = new float[16]; // row-major, data[r*4+c] = M[r][c]
    public ProbeW2S[] world_to_screen;
    public ProbeRay[] screen_to_ray;
}

public class UnityCameraProbe : MonoBehaviour
{
    public Camera targetCamera;
    public Vector3[] worldPoints;

    void Start()
    {
        if (targetCamera == null) targetCamera = Camera.main;
        if (targetCamera == null) { Debug.LogError("no camera"); return; }

        var r = new CameraProbeReport();
        r.unity_version = Application.unityVersion;
        r.screen_width = Screen.width;
        r.screen_height = Screen.height;
        r.fov_y_deg = targetCamera.fieldOfView;
        r.pixel_width = targetCamera.pixelWidth;
        r.pixel_height = targetCamera.pixelHeight;
        r.pixel_rect = new float[] {
            targetCamera.pixelRect.x, targetCamera.pixelRect.y,
            targetCamera.pixelRect.width, targetCamera.pixelRect.height
        };
        r.aspect = targetCamera.aspect;
        r.projection_type = targetCamera.orthographic ? "orthographic" : "perspective";
        r.use_physical_properties = targetCamera.usePhysicalProperties;

        var t = targetCamera.transform;
        r.camera_position = new ProbeVec3(t.position);
        r.camera_forward = new ProbeVec3(t.forward);
        r.camera_up = new ProbeVec3(t.up);
        r.camera_right = new ProbeVec3(t.right);

        var m = t.localToWorldMatrix;
        // 显式 row-major（避免单下标索引器的行/列序歧义）
        r.camera_to_world = new float[] {
            m.m00, m.m01, m.m02, m.m03,
            m.m10, m.m11, m.m12, m.m13,
            m.m20, m.m21, m.m22, m.m23,
            m.m30, m.m31, m.m32, m.m33
        };

        var w2s = new List<ProbeW2S>();
        foreach (var p in worldPoints)
        {
            Vector3 sp = targetCamera.WorldToScreenPoint(p);
            w2s.Add(new ProbeW2S {
                world = new float[] { p.x, p.y, p.z },
                screen = new float[] { sp.x, sp.y, sp.z }
            });
        }
        r.world_to_screen = w2s.ToArray();

        float cx = Screen.width / 2f, cy = Screen.height / 2f;
        float[][] pixels = new float[][] {
            new float[] { cx, cy },
            new float[] { cx + 100f, cy },
            new float[] { cx, cy + 100f },
        };
        var rays = new List<ProbeRay>();
        foreach (var px in pixels)
        {
            Ray ray = targetCamera.ScreenPointToRay(new Vector3(px[0], px[1], 0f));
            rays.Add(new ProbeRay {
                pixel = new float[] { px[0], px[1] },
                origin = new float[] { ray.origin.x, ray.origin.y, ray.origin.z },
                direction = new float[] { ray.direction.x, ray.direction.y, ray.direction.z }
            });
        }
        r.screen_to_ray = rays.ToArray();

        string json = JsonUtility.ToJson(r, true);
        string path = System.IO.Path.Combine(Application.persistentDataPath, "camera_probe.json");
        System.IO.File.WriteAllText(path, json);
        Debug.Log("camera_probe written to " + path);
    }
}
