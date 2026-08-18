using System.Collections.Generic;
using Meta.XR.MRUtilityKit;
using UnityEngine;

namespace EnchantedNightGarden
{
    /// <summary>
    /// Owns the guarantee that you can always tell where real objects are.
    ///
    /// POLICY: highlight-instead-of-hide (chosen 2026-08-09).
    /// Real edges get MORE decoration, not less. Glowing moss along the bed edge,
    /// luminous mushrooms at the desk corner. The intent is that real edges become
    /// the brightest, most legible things in the room -- safer than bare passthrough,
    /// not merely as safe.
    ///
    /// This module has VETO POWER. Every placement request from GardenGenerator
    /// passes through Evaluate() and can be rejected or attenuated. In Phase 1
    /// there is no generator yet, so this exists to (a) prove the hazard edges are
    /// extracted correctly from the room scan and (b) be visible in the wireframe
    /// so we can see whether the highlight curve actually reads as "edge here".
    /// </summary>
    public class SafetyPolicy : MonoBehaviour
    {
        /// <summary>A real-world edge a person could walk into or trip over.</summary>
        public readonly struct Hazard
        {
            public readonly Vector3 Position;
            public readonly float Radius;
            public readonly string Source;

            public Hazard(Vector3 position, float radius, string source)
            {
                Position = position;
                Radius = radius;
                Source = source;
            }
        }

        [Header("Hazard extraction")]
        [Tooltip("Volumes larger than this are treated as furniture worth highlighting.")]
        [SerializeField] private float _minVolumeSize = 0.25f;

        [Tooltip("How far from an edge the highlight still has any effect.")]
        [SerializeField] private float _highlightRange = 0.6f;

        [Header("Debug")]
        [SerializeField] private bool _drawHazards = true;

        private readonly List<Hazard> _hazards = new();
        public IReadOnlyList<Hazard> Hazards => _hazards;

        public void BuildFromRoom(MRUKRoom room)
        {
            _hazards.Clear();

            foreach (MRUKAnchor anchor in room.Anchors)
            {
                if (!anchor.VolumeBounds.HasValue) continue;

                Bounds b = anchor.VolumeBounds.Value;
                if (b.size.magnitude < _minVolumeSize) continue;

                // Sample the top rim of each furniture volume. The top rim is what
                // you actually collide with -- hips against a desk edge, shins
                // against a bed frame -- far more than the volume's centre.
                foreach (Vector3 corner in TopRim(b))
                {
                    _hazards.Add(new Hazard(
                        anchor.transform.TransformPoint(corner),
                        _highlightRange,
                        anchor.Label.ToString()));
                }
            }

            Debug.Log($"[Garden] SafetyPolicy extracted {_hazards.Count} hazard points.");
        }

        /// <summary>
        /// How strongly a decoration at this position should glow, 0..1.
        /// Decoration systems multiply their emissive intensity by this.
        /// </summary>
        public float GetHighlight(Vector3 worldPos)
        {
            float strongest = 0f;

            foreach (Hazard hazard in _hazards)
            {
                float distance = Vector3.Distance(worldPos, hazard.Position);
                if (distance > hazard.Radius) continue;

                float normalized = distance / hazard.Radius; // 0 = on the edge, 1 = at the limit
                strongest = Mathf.Max(strongest, HighlightCurve(normalized));
            }

            return Mathf.Clamp01(strongest);
        }

        // ─────────────────────────────────────────────────────────────────────
        // TODO (Ari): this function defines how the safety policy actually FEELS.
        //
        // Input:  normalizedDistance, 0 = exactly on a real edge, 1 = at the outer
        //         limit of the highlight range (_highlightRange, default 0.6m).
        // Output: glow strength 0..1, which multiplies a decoration's emissive.
        //
        // Three shapes worth considering, and they read very differently in a
        // dark room at 2am:
        //
        //   Linear         return 1f - normalizedDistance;
        //                  Even gradient. Safe, slightly bland, and because it
        //                  never reaches zero abruptly it can wash the whole area
        //                  in dim glow rather than marking a specific line.
        //
        //   Sharp band     return Mathf.SmoothStep(1f, 0f, normalizedDistance * 2f);
        //                  Glow concentrated tightly on the edge itself. Reads
        //                  clearly as "the edge is HERE" but can look like a
        //                  strip light rather than something growing there.
        //
        //   Soft shoulder  return Mathf.Pow(1f - normalizedDistance, 2.5f);
        //                  Bright right at the edge, falling off fast. Organic --
        //                  moss thickest where it meets the furniture. My guess
        //                  at the best balance of legible and pretty, but it is
        //                  a guess and you are the one navigating this room.
        //
        // You could also add a slow pulse for anything labelled OTHER (unknown
        // obstacles), so unidentified things breathe gently and read as
        // "careful, I do not know what this is".
        //
        // Write whatever you think will keep you from barking your shin.
        // ─────────────────────────────────────────────────────────────────────
        private float HighlightCurve(float normalizedDistance)
        {
            // Placeholder so the project compiles. Replace me.
            return Mathf.Pow(1f - normalizedDistance, 2.5f);
        }

        /// <summary>
        /// The veto. Phase 1 has no generator, so nothing calls this yet -- it is
        /// here so that when GardenGenerator arrives in Phase 3 the contract
        /// already exists and cannot be quietly skipped.
        /// </summary>
        public bool Evaluate(Vector3 worldPos, out float glowMultiplier)
        {
            glowMultiplier = 1f + GetHighlight(worldPos) * 2f;

            // Under highlight-instead-of-hide nothing is rejected outright --
            // hazards get MORE decoration. Rejection stays available for the one
            // case it is still needed: the floor path, added in Phase 2.
            return true;
        }

        private static IEnumerable<Vector3> TopRim(Bounds b)
        {
            Vector3 c = b.center;
            Vector3 e = b.extents;

            yield return c + new Vector3(-e.x, e.y, -e.z);
            yield return c + new Vector3(e.x, e.y, -e.z);
            yield return c + new Vector3(e.x, e.y, e.z);
            yield return c + new Vector3(-e.x, e.y, e.z);
        }

        private void OnDrawGizmos()
        {
            if (!_drawHazards) return;

            Gizmos.color = new Color(1f, 0.4f, 0.4f, 0.6f);
            foreach (Hazard hazard in _hazards)
            {
                Gizmos.DrawWireSphere(hazard.Position, 0.05f);
            }
        }
    }
}
