using System;
using System.Collections.Generic;
using System.IO;
using System.Threading.Tasks;
using Meta.XR.MRUtilityKit;
using UnityEngine;

namespace EnchantedNightGarden
{
    /// <summary>
    /// Places exactly two things -- one glowing flower on the floor, one vine
    /// segment on a wall -- anchors them, and brings them back tomorrow night.
    ///
    /// This is the load-bearing test of the whole prototype (PROTOTYPE.md criteria
    /// 2 and 3). If the flower is not in the same physical spot on the second
    /// night, nothing built on top of it will work either.
    ///
    /// We persist UUIDs to JSON and let Horizon OS persist the actual anchors.
    /// Per ARCHITECTURE.md we never serialise transforms -- the anchor system is
    /// the source of truth for where things are.
    /// </summary>
    public class AnchorPlanter : MonoBehaviour
    {
        [Header("Prefabs")]
        [Tooltip("Phase 1: an emissive sphere is fine. No authored art yet.")]
        [SerializeField] private GameObject _flowerPrefab;
        [SerializeField] private GameObject _vinePrefab;

        [Header("Controls")]
        [SerializeField] private OVRInput.RawButton _placeButton = OVRInput.RawButton.X;
        [SerializeField] private OVRInput.RawButton _clearButton = OVRInput.RawButton.Y;

        [Header("Drift measurement")]
        [Tooltip("Recorded at session start; DebugOverlay reports how far it has moved since.")]
        public Vector3 FlowerPositionAtSessionStart { get; private set; }
        public bool HasFlower => _flower != null;
        public Vector3 FlowerPosition => _flower != null ? _flower.transform.position : Vector3.zero;

        private OVRSpatialAnchor _flower;
        private OVRSpatialAnchor _vine;
        private MRUKRoom _room;
        private string SavePath => Path.Combine(Application.persistentDataPath, "planted.json");

        [Serializable]
        private class SavedAnchors
        {
            public string flowerUuid;
            public string vineUuid;
        }

        public void OnRoomReady(MRUKRoom room)
        {
            _room = room;
            _ = RestoreAsync();
        }

        private void Update()
        {
            if (OVRInput.GetDown(_placeButton) && _room != null)
            {
                _ = PlantAsync();
            }

            if (OVRInput.GetDown(_clearButton))
            {
                _ = ClearAsync();
            }
        }

        public void ApplyIntensity(float intensity)
        {
            if (_flower != null) _flower.gameObject.SetActive(intensity > 0.05f);
            if (_vine != null) _vine.gameObject.SetActive(intensity > 0.05f);
        }

        // ── Planting ────────────────────────────────────────────────────────

        private async Task PlantAsync()
        {
            await ClearAsync();

            // Flower: on the floor, a little in front of where you are looking.
            // FloorAnchor (singular) is deprecated -- High Fidelity Scene allowed
            // multiple floors. One bedroom has one floor, so take the first.
            MRUKAnchor floor = _room.FloorAnchors != null && _room.FloorAnchors.Count > 0
                ? _room.FloorAnchors[0]
                : null;

            if (floor != null && Camera.main != null)
            {
                Vector3 ahead = Camera.main.transform.position + Camera.main.transform.forward * 1.2f;
                floor.GetClosestSurfacePosition(ahead, out Vector3 floorPoint);
                _flower = await CreateAnchorAsync(_flowerPrefab, floorPoint, Quaternion.identity, "flower");
                if (_flower != null) FlowerPositionAtSessionStart = _flower.transform.position;
            }

            // Vine: on the longest unobstructed wall, at roughly eye height.
            MRUKAnchor wall = _room.GetKeyWall(out Vector2 _);
            if (wall != null)
            {
                Vector3 wallPoint = wall.transform.position;
                Quaternion facing = Quaternion.LookRotation(wall.transform.forward);
                _vine = await CreateAnchorAsync(_vinePrefab, wallPoint, facing, "vine");
            }

            Save();
        }

        private async Task<OVRSpatialAnchor> CreateAnchorAsync(
            GameObject prefab, Vector3 position, Quaternion rotation, string label)
        {
            if (prefab == null)
            {
                Debug.LogWarning($"[Garden] No prefab assigned for {label}.");
                return null;
            }

            GameObject go = Instantiate(prefab, position, rotation);
            go.name = $"anchored_{label}";

            var anchor = go.AddComponent<OVRSpatialAnchor>();

            // Creation is async; the UUID is not valid until Created flips true.
            while (!anchor.Created)
            {
                await Task.Yield();
            }

            var result = await anchor.SaveAnchorAsync();
            if (!result.Success)
            {
                Debug.LogError($"[Garden] Failed to save {label} anchor: {result.Status}");
            }
            else
            {
                Debug.Log($"[Garden] Saved {label} anchor {anchor.Uuid}");
            }

            return anchor;
        }

        // ── Restoring ───────────────────────────────────────────────────────

        private async Task RestoreAsync()
        {
            if (!File.Exists(SavePath))
            {
                Debug.Log("[Garden] No saved anchors. Press X to plant.");
                return;
            }

            SavedAnchors saved;
            try
            {
                saved = JsonUtility.FromJson<SavedAnchors>(File.ReadAllText(SavePath));
            }
            catch (Exception e)
            {
                Debug.LogError($"[Garden] Could not read {SavePath}: {e.Message}");
                return;
            }

            var uuids = new List<Guid>();
            if (TryParse(saved.flowerUuid, out Guid f)) uuids.Add(f);
            if (TryParse(saved.vineUuid, out Guid v)) uuids.Add(v);
            if (uuids.Count == 0) return;

            var unbound = new List<OVRSpatialAnchor.UnboundAnchor>();
            var result = await OVRSpatialAnchor.LoadUnboundAnchorsAsync(uuids, unbound);

            if (!result.Success)
            {
                Debug.LogError($"[Garden] Anchor load failed: {result.Status}");
                return;
            }

            foreach (OVRSpatialAnchor.UnboundAnchor ua in unbound)
            {
                bool localized = await ua.LocalizeAsync();
                if (!localized)
                {
                    Debug.LogWarning($"[Garden] Could not localize {ua.Uuid}. " +
                                     "Usually means you are not in the scanned room yet.");
                    continue;
                }

                bool isFlower = ua.Uuid.ToString() == saved.flowerUuid;
                GameObject prefab = isFlower ? _flowerPrefab : _vinePrefab;
                if (prefab == null) continue;

                GameObject go = Instantiate(prefab);
                go.name = isFlower ? "anchored_flower" : "anchored_vine";

                var anchor = go.AddComponent<OVRSpatialAnchor>();
                ua.BindTo(anchor);

                if (isFlower)
                {
                    _flower = anchor;
                    FlowerPositionAtSessionStart = go.transform.position;
                }
                else
                {
                    _vine = anchor;
                }
            }

            Debug.Log($"[Garden] Restored {unbound.Count} anchor(s) from last session.");
        }

        // ── Clearing ────────────────────────────────────────────────────────

        private async Task ClearAsync()
        {
            if (_flower != null)
            {
                await _flower.EraseAnchorAsync();
                Destroy(_flower.gameObject);
                _flower = null;
            }

            if (_vine != null)
            {
                await _vine.EraseAnchorAsync();
                Destroy(_vine.gameObject);
                _vine = null;
            }

            if (File.Exists(SavePath)) File.Delete(SavePath);
        }

        private void Save()
        {
            var saved = new SavedAnchors
            {
                flowerUuid = _flower != null ? _flower.Uuid.ToString() : null,
                vineUuid = _vine != null ? _vine.Uuid.ToString() : null
            };

            File.WriteAllText(SavePath, JsonUtility.ToJson(saved));
            Debug.Log($"[Garden] Saved anchor UUIDs to {SavePath}");
        }

        private static bool TryParse(string s, out Guid guid)
        {
            guid = Guid.Empty;
            return !string.IsNullOrEmpty(s) && Guid.TryParse(s, out guid);
        }
    }
}
