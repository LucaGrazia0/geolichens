import math


class SolutionStabilityService:
    """Calcola il Solution Stability Index (SSI) dalla struttura dei cluster spaziali.

    Fase 8.2: l'SSI non dipende piu' soltanto dal secondo candidato. Seleziona le
    soluzioni ecologicamente equivalenti, le raggruppa con un DBSCAN minimale e
    misura la compattezza e la dominanza del cluster che contiene il punto scelto.
    L'indice e' descrittivo e non altera GSS, ranking o punto selezionato.
    """

    def evaluate(
        self,
        center_score,
        features_data,
        center_point,
        distance_func,
        model_radius_m=None,
        grid_step_m=None,
    ):
        rows = list(features_data or [])
        center_score = self._float(center_score, 0.0)
        grid_step = max(self._float(grid_step_m, 0.0) or 0.0, 1.0)
        reference_m = max(
            self._float(model_radius_m, 0.0) or 0.0,
            2.0 * grid_step,
            250.0,
        )
        # Soglia spaziale coerente con griglia e raggio del modello. Il cap evita
        # che un raggio molto grande fonda automaticamente localita' separate.
        cluster_eps_m = max(1.5 * grid_step, min(0.75 * reference_m, 500.0), 100.0)

        candidates = []
        for row in rows:
            point = row.get("point")
            score = self._float(row.get("score"), None)
            if point is None or score is None:
                continue
            candidates.append({"point": point, "score": score})

        # Il punto selezionato deve essere sempre il nodo 0 del clustering.
        nodes = [{"point": center_point, "score": center_score, "selected": True}]
        tolerance = max(2.0, abs(center_score) * 0.03)
        for item in candidates:
            if center_score - item["score"] > tolerance:
                continue
            try:
                d_center = distance_func(center_point, item["point"])
            except Exception:
                d_center = None
            if d_center is None or float(d_center) < 0.01:
                continue
            nodes.append({
                "point": item["point"],
                "score": item["score"],
                "selected": False,
                "distance_from_center_m": max(0.0, float(d_center)),
            })

        if len(nodes) == 1:
            return self._single_solution(reference_m, cluster_eps_m)

        labels = self._dbscan(
            nodes=nodes,
            distance_func=distance_func,
            eps_m=cluster_eps_m,
            min_samples=2,
        )
        selected_label = labels[0]
        if selected_label < 0:
            # Un punto selezionato isolato costituisce comunque un cluster proprio.
            selected_label = max(labels, default=-1) + 1
            labels[0] = selected_label

        cluster_members = {}
        for idx, label in enumerate(labels):
            if label < 0:
                # Ogni rumore resta una soluzione spaziale distinta.
                label = max(labels, default=-1) + 1 + idx
            cluster_members.setdefault(label, []).append(idx)

        main_indices = cluster_members.get(selected_label, [0])
        plausible_count = len(nodes) - 1
        total_nodes = len(nodes)
        main_share = len(main_indices) / float(total_nodes)

        main_distances = []
        for idx in main_indices:
            if idx == 0:
                main_distances.append(0.0)
                continue
            value = nodes[idx].get("distance_from_center_m")
            if value is None:
                try:
                    value = distance_func(center_point, nodes[idx]["point"])
                except Exception:
                    value = None
            if value is not None:
                main_distances.append(max(0.0, float(value)))

        cluster_radius = self._percentile(sorted(main_distances), 0.90)
        cluster_median = self._median(sorted(main_distances))
        cluster_count = len(cluster_members)

        competing_distances = []
        for label, indices in cluster_members.items():
            if label == selected_label:
                continue
            for idx in indices:
                try:
                    value = distance_func(center_point, nodes[idx]["point"])
                except Exception:
                    value = None
                if value is not None:
                    competing_distances.append(max(0.0, float(value)))
        nearest_competing_cluster_m = min(competing_distances) if competing_distances else None

        compactness = math.exp(-cluster_radius / max(reference_m, 1.0))
        dominance = main_share
        if nearest_competing_cluster_m is None:
            separation = 1.0
        else:
            separation = 1.0 - math.exp(-nearest_competing_cluster_m / max(reference_m, 1.0))

        # La stabilita' cresce soprattutto se il cluster principale e' compatto e
        # contiene gran parte delle soluzioni equivalenti. La separazione tra nuclei
        # ha un peso secondario e non puo' compensare un cluster principale debole.
        numeric = 100.0 * (
            0.50 * compactness
            + 0.40 * dominance
            + 0.10 * separation
        )
        numeric = max(0.0, min(100.0, numeric))

        reasons = self._reasons(
            cluster_radius=cluster_radius,
            cluster_median=cluster_median,
            main_share=main_share,
            main_count=len(main_indices),
            plausible_count=plausible_count,
            cluster_count=cluster_count,
            nearest_competing_cluster_m=nearest_competing_cluster_m,
            reference_m=reference_m,
        )

        # Campi storici mantenuti come alias per retrocompatibilita'.
        second_distance = min(
            (node.get("distance_from_center_m") for node in nodes[1:]),
            default=None,
        )
        return {
            "solution_stability_index": round(numeric, 1),
            "solution_stability_class": self._label(numeric),
            "solution_stability_reasons": reasons,
            "solution_stability_method": "SSI_v2_ecological_equivalent_dbscan_clusters",
            "ssi_cluster_count": int(cluster_count),
            "ssi_main_cluster_count": int(len(main_indices)),
            "ssi_main_cluster_share": round(main_share, 4),
            "ssi_main_cluster_radius_m": round(cluster_radius, 1),
            "ssi_main_cluster_median_m": round(cluster_median, 1),
            "ssi_cluster_eps_m": round(cluster_eps_m, 1),
            "ssi_nearest_competing_cluster_m": (
                round(nearest_competing_cluster_m, 1)
                if nearest_competing_cluster_m is not None else None
            ),
            "leave_one_out_distance_m": (
                round(second_distance, 1) if second_distance is not None else None
            ),
            "plausible_alternative_spread_m": round(cluster_radius, 1),
            "plausible_alternative_count": int(plausible_count),
            "ssi_reference_m": round(reference_m, 1),
        }

    def _single_solution(self, reference_m, cluster_eps_m):
        return {
            "solution_stability_index": 100.0,
            "solution_stability_class": "very_high",
            "solution_stability_reasons": [
                "un solo nucleo plausibile: nessuna alternativa ecologicamente equivalente distinta"
            ],
            "solution_stability_method": "SSI_v2_ecological_equivalent_dbscan_clusters",
            "ssi_cluster_count": 1,
            "ssi_main_cluster_count": 1,
            "ssi_main_cluster_share": 1.0,
            "ssi_main_cluster_radius_m": 0.0,
            "ssi_main_cluster_median_m": 0.0,
            "ssi_cluster_eps_m": round(cluster_eps_m, 1),
            "ssi_nearest_competing_cluster_m": None,
            "leave_one_out_distance_m": None,
            "plausible_alternative_spread_m": 0.0,
            "plausible_alternative_count": 0,
            "ssi_reference_m": round(reference_m, 1),
        }

    def _dbscan(self, nodes, distance_func, eps_m, min_samples=2):
        """DBSCAN minimale, senza dipendenze esterne, adatto ai candidati QGIS."""
        count = len(nodes)
        unvisited = None
        noise = -1
        labels = [unvisited] * count
        cluster_id = 0
        neighbour_cache = {}

        def neighbours(index):
            if index in neighbour_cache:
                return neighbour_cache[index]
            result = []
            point = nodes[index]["point"]
            for other_index, other in enumerate(nodes):
                try:
                    distance = distance_func(point, other["point"])
                except Exception:
                    distance = None
                if distance is not None and float(distance) <= eps_m:
                    result.append(other_index)
            neighbour_cache[index] = result
            return result

        visited = [False] * count
        for index in range(count):
            if visited[index]:
                continue
            visited[index] = True
            nearby = neighbours(index)
            if len(nearby) < min_samples:
                labels[index] = noise
                continue

            labels[index] = cluster_id
            queue = list(nearby)
            queued = set(queue)
            cursor = 0
            while cursor < len(queue):
                neighbour_index = queue[cursor]
                cursor += 1
                if not visited[neighbour_index]:
                    visited[neighbour_index] = True
                    neighbour_nearby = neighbours(neighbour_index)
                    if len(neighbour_nearby) >= min_samples:
                        for value in neighbour_nearby:
                            if value not in queued:
                                queue.append(value)
                                queued.add(value)
                if labels[neighbour_index] is None or labels[neighbour_index] == noise:
                    labels[neighbour_index] = cluster_id
            cluster_id += 1

        return [noise if value is None else value for value in labels]

    def _reasons(
        self,
        cluster_radius,
        cluster_median,
        main_share,
        main_count,
        plausible_count,
        cluster_count,
        nearest_competing_cluster_m,
        reference_m,
    ):
        if cluster_radius <= 0.35 * reference_m:
            compactness = "cluster principale molto compatto"
        elif cluster_radius <= 0.8 * reference_m:
            compactness = "cluster principale compatto"
        elif cluster_radius <= 1.5 * reference_m:
            compactness = "cluster principale moderatamente disperso"
        else:
            compactness = "cluster principale molto disperso"

        if main_share >= 0.80:
            dominance = "la grande maggioranza delle soluzioni ricade nel cluster principale"
        elif main_share >= 0.60:
            dominance = "la maggioranza delle soluzioni ricade nel cluster principale"
        elif main_share >= 0.40:
            dominance = "le soluzioni sono ripartite tra piu' cluster"
        else:
            dominance = "il cluster selezionato contiene una quota minoritaria delle soluzioni"

        cluster_text = f"{cluster_count} cluster spaziali rilevati"
        if nearest_competing_cluster_m is not None:
            cluster_text += f"; il piu' vicino e' a {nearest_competing_cluster_m:.0f} m"
        else:
            cluster_text = "un unico cluster spaziale rilevato"

        return [
            f"{compactness} (raggio 90% {cluster_radius:.0f} m; mediana {cluster_median:.0f} m)",
            f"{dominance} ({main_count}/{plausible_count + 1}, {main_share * 100.0:.0f}%)",
            cluster_text,
        ]

    @staticmethod
    def _percentile(values, fraction):
        if not values:
            return 0.0
        if len(values) == 1:
            return float(values[0])
        position = (len(values) - 1) * fraction
        lower = int(math.floor(position))
        upper = int(math.ceil(position))
        if lower == upper:
            return float(values[lower])
        weight = position - lower
        return float(values[lower]) * (1.0 - weight) + float(values[upper]) * weight

    @staticmethod
    def _median(values):
        if not values:
            return 0.0
        middle = len(values) // 2
        if len(values) % 2:
            return float(values[middle])
        return (float(values[middle - 1]) + float(values[middle])) / 2.0

    @staticmethod
    def _label(value):
        if value >= 80:
            return "very_high"
        if value >= 65:
            return "high"
        if value >= 50:
            return "medium"
        if value >= 35:
            return "low"
        return "very_low"

    @staticmethod
    def _float(value, default=None):
        try:
            return float(value)
        except Exception:
            return default
