using System.Collections.Generic;
using System.Text;
using Meta.XR.MRUtilityKit;
using UnityEngine;

namespace EnchantedNightGarden
{
    /// <summary>
    /// Draws a glowing outline over every detected plane and volume, with its
    /// semantic label rendered beside it in world space.
    ///
    /// This is a measuring instrument, not a view. Ugly is fine. Its job is to
    /// answer two questions: does the scan line up with the real room, and what
    /// did Space Setup actually call my furniture (UNKNOWNS.md Test #3).
    ///
    /// Note on labels: we render anchor.Label.ToString() rather than comparing
    /// against hardcoded enum members, so this works regardless of how the label
    /// enum is spelled in your installed SDK version. That is the whole point --
    /// we are here to discover the names, not assume them.
    /// </summary>
    public class RoomWireframe : MonoBehaviour
    {
        [SerializeField] private Material _lineMaterial;
        [SerializeField] private Color _planeColor = new Color(0.55f, 0.75f, 1f);
        [SerializeField] private Color _volumeColor = new Color(1f, 0.65f, 0.9f);
        [SerializeField] private bool _showLabels = true;
        [SerializeField] private float _labelSize = 0.04f;

        private readonly List<LineRenderer> _lines = new();
        private readonly List<TextMesh> _labels = new();
        private readonly StringBuilder _report = new();

        /// <summary>Human-readable dump of every anchor and its label. Printed once, shown in the overlay.</summary>
        public string LabelReport { get; private set; } = "(room not loaded)";

        public void BuildFromRoom(MRUKRoom room)
        {
            Clear();
            _report.Clear();
            _report.AppendLine($"ROOM: {room.Anchors.Count} anchors");

            foreach (MRUKAnchor anchor in room.Anchors)
            {
                string label = anchor.Label.ToString();
                // VolumeBounds/PlaneRect are nullable; HasVolume/HasPlane are deprecated
                // in favour of checking HasValue directly.
                string kind = anchor.VolumeBounds.HasValue ? "volume"
                    : anchor.PlaneRect.HasValue ? "plane" : "none";
                _report.AppendLine($"  {label}  [{kind}]");

                if (anchor.VolumeBounds.HasValue)
                {
                    DrawBox(anchor.transform, anchor.VolumeBounds.Value, _volumeColor);
                }
                else if (anchor.PlaneRect.HasValue)
                {
                    DrawRect(anchor.transform, anchor.PlaneRect.Value, _planeColor);
                }

                if (_showLabels)
                {
                    SpawnLabel(anchor, label);
                }
            }

            LabelReport = _report.ToString();
            Debug.Log("[Garden] " + LabelReport);
        }

        public void ApplyIntensity(float intensity)
        {
            foreach (LineRenderer line in _lines)
            {
                if (line != null) line.enabled = intensity > 0.05f;
            }
            foreach (TextMesh label in _labels)
            {
                if (label != null) label.gameObject.SetActive(intensity > 0.05f);
            }
        }

        private void DrawRect(Transform anchorTransform, Rect rect, Color color)
        {
            Vector3[] corners =
            {
                new(rect.xMin, rect.yMin, 0f),
                new(rect.xMax, rect.yMin, 0f),
                new(rect.xMax, rect.yMax, 0f),
                new(rect.xMin, rect.yMax, 0f)
            };

            for (int i = 0; i < corners.Length; i++)
            {
                corners[i] = anchorTransform.TransformPoint(corners[i]);
            }

            NewLine(corners, color, closed: true);
        }

        private void DrawBox(Transform anchorTransform, Bounds bounds, Color color)
        {
            Vector3 c = bounds.center;
            Vector3 e = bounds.extents;

            Vector3[] local =
            {
                c + new Vector3(-e.x, -e.y, -e.z), c + new Vector3(e.x, -e.y, -e.z),
                c + new Vector3(e.x, -e.y, e.z),   c + new Vector3(-e.x, -e.y, e.z),
                c + new Vector3(-e.x, e.y, -e.z),  c + new Vector3(e.x, e.y, -e.z),
                c + new Vector3(e.x, e.y, e.z),    c + new Vector3(-e.x, e.y, e.z)
            };

            for (int i = 0; i < local.Length; i++)
            {
                local[i] = anchorTransform.TransformPoint(local[i]);
            }

            NewLine(new[] { local[0], local[1], local[2], local[3] }, color, closed: true);
            NewLine(new[] { local[4], local[5], local[6], local[7] }, color, closed: true);
            for (int i = 0; i < 4; i++)
            {
                NewLine(new[] { local[i], local[i + 4] }, color, closed: false);
            }
        }

        private void NewLine(Vector3[] points, Color color, bool closed)
        {
            var go = new GameObject("wire");
            go.transform.SetParent(transform, false);

            var lr = go.AddComponent<LineRenderer>();
            lr.material = _lineMaterial;
            lr.startColor = lr.endColor = color;
            lr.widthMultiplier = 0.006f;
            lr.useWorldSpace = true;
            lr.loop = closed;
            lr.positionCount = points.Length;
            lr.SetPositions(points);
            lr.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
            lr.receiveShadows = false;

            _lines.Add(lr);
        }

        private void SpawnLabel(MRUKAnchor anchor, string text)
        {
            var go = new GameObject($"label_{text}");
            go.transform.SetParent(transform, false);
            go.transform.position = anchor.transform.position;

            var tm = go.AddComponent<TextMesh>();
            tm.text = text;
            tm.characterSize = _labelSize;
            tm.fontSize = 96;
            tm.anchor = TextAnchor.MiddleCenter;
            tm.color = Color.white;

            go.AddComponent<FaceCamera>();
            _labels.Add(tm);
        }

        private void Clear()
        {
            foreach (LineRenderer line in _lines)
            {
                if (line != null) Destroy(line.gameObject);
            }
            foreach (TextMesh label in _labels)
            {
                if (label != null) Destroy(label.gameObject);
            }
            _lines.Clear();
            _labels.Clear();
        }
    }

    /// <summary>Keeps world-space debug text readable from wherever you are standing.</summary>
    public class FaceCamera : MonoBehaviour
    {
        private Transform _cam;

        private void LateUpdate()
        {
            if (_cam == null)
            {
                if (Camera.main == null) return;
                _cam = Camera.main.transform;
            }

            transform.rotation = Quaternion.LookRotation(transform.position - _cam.position);
        }
    }
}
