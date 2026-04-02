/**
 * DAG Diagram Renderer
 *
 * Reads graph JSON from #dag-graph-data, runs dagre layout,
 * renders positioned SVG into #dag-diagram container.
 *
 * Dependencies: dagre.min.js must be loaded first.
 */
(function () {
    'use strict';

    var CONFIG = {
        rankdir: 'LR',
        ranksep: 60,
        nodesep: 30,
        edgesep: 20,
        marginx: 20,
        marginy: 20,
        nodeHeight: 40,
        minNodeWidth: 100,
        charWidth: 7.5,
        diamondSize: 70,
    };

    var STATUS_COLORS = {
        completed:  { fill: '#d1fae5', stroke: '#059669' },
        running:    { fill: '#dbeafe', stroke: '#0071BC' },
        failed:     { fill: '#fee2e2', stroke: '#dc2626' },
        pending:    { fill: '#f1f5f9', stroke: '#cbd5e1' },
        ready:      { fill: '#f1f5f9', stroke: '#94a3b8' },
        waiting:    { fill: '#fef3c7', stroke: '#f59e0b' },
        skipped:    { fill: '#f1f5f9', stroke: '#cbd5e1' },
        expanded:   { fill: '#ede9fe', stroke: '#8b5cf6' },
        cancelled:  { fill: '#f1f5f9', stroke: '#cbd5e1' },
        definition: { fill: '#f0f9ff', stroke: '#0284c7' },
    };

    var TYPE_COLORS = {
        task:        { fill: '#f0f9ff', stroke: '#0284c7' },
        conditional: { fill: '#fffbeb', stroke: '#d97706' },
        fan_out:     { fill: '#f5f3ff', stroke: '#8b5cf6' },
        fan_in:      { fill: '#f5f3ff', stroke: '#8b5cf6' },
        gate:        { fill: '#fffbeb', stroke: '#f59e0b' },
    };

    function nodeWidth(label) {
        return Math.max(label.length * CONFIG.charWidth + 24, CONFIG.minNodeWidth);
    }

    function getColors(node) {
        if (node.status === 'definition') {
            return TYPE_COLORS[node.type] || TYPE_COLORS.task;
        }
        return STATUS_COLORS[node.status] || STATUS_COLORS.pending;
    }

    function svgEl(tag, attrs) {
        var el = document.createElementNS('http://www.w3.org/2000/svg', tag);
        if (attrs) {
            for (var k in attrs) {
                el.setAttribute(k, attrs[k]);
            }
        }
        return el;
    }

    function renderRect(svg, x, y, w, h, colors, label) {
        var rect = svgEl('rect', {
            x: x - w / 2, y: y - h / 2,
            width: w, height: h, rx: 6,
            fill: colors.fill, stroke: colors.stroke, 'stroke-width': '1.5',
        });
        svg.appendChild(rect);
        var text = svgEl('text', {
            x: x, y: y + 4,
            'text-anchor': 'middle', fill: colors.stroke,
            'font-size': '11', 'font-weight': '500',
        });
        text.textContent = label;
        svg.appendChild(text);
        return rect;
    }

    function renderDiamond(svg, x, y, size, colors, label) {
        var hs = size / 2;
        var points = [x, y - hs, x + hs, y, x, y + hs, x - hs, y].join(',');
        var poly = svgEl('polygon', {
            points: points,
            fill: colors.fill, stroke: colors.stroke, 'stroke-width': '1.5',
        });
        svg.appendChild(poly);
        var text = svgEl('text', {
            x: x, y: y + 4,
            'text-anchor': 'middle', fill: colors.stroke,
            'font-size': '10', 'font-weight': '500',
        });
        text.textContent = label.length > 12 ? label.substring(0, 11) + '\u2026' : label;
        svg.appendChild(text);
    }

    function renderTrapezoid(svg, x, y, w, h, colors, label, inverted) {
        var hw = w / 2, hh = h / 2;
        var inset = 10;
        var pts;
        if (inverted) {
            pts = [x - hw + inset, y - hh, x + hw - inset, y - hh, x + hw, y + hh, x - hw, y + hh];
        } else {
            pts = [x - hw, y - hh, x + hw, y - hh, x + hw - inset, y + hh, x - hw + inset, y + hh];
        }
        var poly = svgEl('polygon', {
            points: pts.join(','),
            fill: colors.fill, stroke: colors.stroke, 'stroke-width': '1.5',
        });
        svg.appendChild(poly);
        var text = svgEl('text', {
            x: x, y: y + 4,
            'text-anchor': 'middle', fill: colors.stroke,
            'font-size': '10', 'font-weight': '500',
        });
        text.textContent = label;
        svg.appendChild(text);
    }

    function renderOctagon(svg, x, y, w, h, colors, label) {
        var hw = w / 2, hh = h / 2;
        var cut = 10;
        var pts = [
            x - hw + cut, y - hh,
            x + hw - cut, y - hh,
            x + hw, y - hh + cut,
            x + hw, y + hh - cut,
            x + hw - cut, y + hh,
            x - hw + cut, y + hh,
            x - hw, y + hh - cut,
            x - hw, y - hh + cut,
        ];
        var poly = svgEl('polygon', {
            points: pts.join(','),
            fill: colors.fill, stroke: colors.stroke, 'stroke-width': '2',
        });
        svg.appendChild(poly);
        var text = svgEl('text', {
            x: x, y: y + 4,
            'text-anchor': 'middle', fill: colors.stroke,
            'font-size': '10', 'font-weight': '600',
        });
        text.textContent = label;
        svg.appendChild(text);
    }

    function renderStatusBadge(svg, x, y, w, h, status) {
        var bx = x + w / 2 - 2;
        var by = y - h / 2 - 2;
        var r = 7;

        if (status === 'completed' || status === 'expanded') {
            var circle = svgEl('circle', { cx: bx, cy: by, r: r, fill: '#059669' });
            svg.appendChild(circle);
            var check = svgEl('text', { x: bx, y: by + 4, 'text-anchor': 'middle', fill: 'white', 'font-size': '10', 'font-weight': 'bold' });
            check.textContent = '\u2713';
            svg.appendChild(check);
        } else if (status === 'failed') {
            var c2 = svgEl('circle', { cx: bx, cy: by, r: r, fill: '#dc2626' });
            svg.appendChild(c2);
            var xm = svgEl('text', { x: bx, y: by + 4, 'text-anchor': 'middle', fill: 'white', 'font-size': '10', 'font-weight': 'bold' });
            xm.textContent = '\u2715';
            svg.appendChild(xm);
        } else if (status === 'running') {
            var c3 = svgEl('circle', { cx: bx, cy: by, r: r, fill: '#0071BC' });
            svg.appendChild(c3);
            var anim = svgEl('animate', { attributeName: 'r', values: '6;8;6', dur: '1.5s', repeatCount: 'indefinite' });
            c3.appendChild(anim);
            var play = svgEl('text', { x: bx, y: by + 3.5, 'text-anchor': 'middle', fill: 'white', 'font-size': '8', 'font-weight': 'bold' });
            play.textContent = '\u25B6';
            svg.appendChild(play);
        } else if (status === 'waiting') {
            var c4 = svgEl('circle', { cx: bx, cy: by, r: r, fill: '#f59e0b' });
            svg.appendChild(c4);
            var pause = svgEl('text', { x: bx, y: by + 4, 'text-anchor': 'middle', fill: 'white', 'font-size': '9', 'font-weight': 'bold' });
            pause.textContent = '\u23F8';
            svg.appendChild(pause);
        } else if (status === 'skipped') {
            var c5 = svgEl('circle', { cx: bx, cy: by, r: r, fill: '#94a3b8' });
            svg.appendChild(c5);
            var dash = svgEl('text', { x: bx, y: by + 4, 'text-anchor': 'middle', fill: 'white', 'font-size': '12', 'font-weight': 'bold' });
            dash.textContent = '\u2013';
            svg.appendChild(dash);
        }
    }

    function renderEdge(svg, points, optional, label) {
        var d = 'M ' + points[0].x + ',' + points[0].y;
        if (points.length === 2) {
            d += ' L ' + points[1].x + ',' + points[1].y;
        } else if (points.length >= 3) {
            for (var i = 1; i < points.length - 1; i++) {
                var cp = points[i];
                var end = (i < points.length - 2)
                    ? { x: (cp.x + points[i + 1].x) / 2, y: (cp.y + points[i + 1].y) / 2 }
                    : points[i + 1];
                d += ' Q ' + cp.x + ',' + cp.y + ' ' + end.x + ',' + end.y;
            }
        }

        var attrs = {
            d: d, fill: 'none',
            stroke: optional ? '#cbd5e1' : '#94a3b8',
            'stroke-width': '1.5',
            'marker-end': optional ? 'url(#arrow-opt)' : 'url(#arrow)',
        };
        if (optional) {
            attrs['stroke-dasharray'] = '5,3';
        }
        svg.appendChild(svgEl('path', attrs));

        if (label) {
            var mid = points[Math.floor(points.length / 2)];
            var labelEl = svgEl('text', {
                x: mid.x, y: mid.y - 8,
                'text-anchor': 'middle', fill: '#6b7280',
                'font-size': '9', 'font-style': 'italic',
            });
            labelEl.textContent = label;
            svg.appendChild(labelEl);
        }
    }

    function renderDiagram(containerId, dataId) {
        var dataEl = document.getElementById(dataId);
        if (!dataEl) return;

        var graphData;
        try {
            graphData = JSON.parse(dataEl.textContent);
        } catch (e) {
            return;
        }

        if (!graphData || !graphData.nodes || graphData.nodes.length === 0) {
            var container = document.getElementById(containerId);
            if (container) container.innerHTML = '<p style="color: #94a3b8; padding: 16px;">No workflow definition available.</p>';
            return;
        }

        var g = new dagre.graphlib.Graph();
        g.setGraph({
            rankdir: CONFIG.rankdir,
            ranksep: CONFIG.ranksep,
            nodesep: CONFIG.nodesep,
            edgesep: CONFIG.edgesep,
            marginx: CONFIG.marginx,
            marginy: CONFIG.marginy,
        });
        g.setDefaultEdgeLabel(function () { return {}; });

        var nodeMap = {};
        graphData.nodes.forEach(function (n) {
            nodeMap[n.id] = n;
            var w, h;
            if (n.type === 'conditional') {
                w = CONFIG.diamondSize;
                h = CONFIG.diamondSize;
            } else {
                w = nodeWidth(n.label);
                h = CONFIG.nodeHeight;
            }
            g.setNode(n.id, { width: w, height: h, label: n.label });
        });

        graphData.edges.forEach(function (e) {
            if (g.hasNode(e.source) && g.hasNode(e.target)) {
                g.setEdge(e.source, e.target, { label: e.label || '', optional: e.optional });
            }
        });

        dagre.layout(g);

        var graph = g.graph();
        var svgWidth = graph.width || 600;
        var svgHeight = graph.height || 200;

        var svg = svgEl('svg', {
            viewBox: '0 0 ' + svgWidth + ' ' + svgHeight,
            width: '100%',
            style: 'min-width: ' + Math.min(svgWidth, 400) + 'px; height: auto; font-family: system-ui, -apple-system, sans-serif;',
        });

        var defs = svgEl('defs');
        var marker = svgEl('marker', {
            id: 'arrow', markerWidth: '8', markerHeight: '6', refX: '8', refY: '3', orient: 'auto',
        });
        marker.appendChild(svgEl('path', { d: 'M0,0 L8,3 L0,6', fill: '#94a3b8' }));
        defs.appendChild(marker);

        var markerOpt = svgEl('marker', {
            id: 'arrow-opt', markerWidth: '8', markerHeight: '6', refX: '8', refY: '3', orient: 'auto',
        });
        markerOpt.appendChild(svgEl('path', { d: 'M0,0 L8,3 L0,6', fill: '#cbd5e1' }));
        defs.appendChild(markerOpt);
        svg.appendChild(defs);

        g.edges().forEach(function (e) {
            var edgeData = g.edge(e);
            var edgeDef = graphData.edges.find(function (ed) {
                return ed.source === e.v && ed.target === e.w;
            });
            renderEdge(svg, edgeData.points, edgeDef ? edgeDef.optional : false, edgeDef ? edgeDef.label : '');
        });

        g.nodes().forEach(function (id) {
            var pos = g.node(id);
            var node = nodeMap[id];
            if (!node) return;

            var colors = getColors(node);
            var w = pos.width, h = pos.height;

            switch (node.type) {
                case 'conditional':
                    renderDiamond(svg, pos.x, pos.y, CONFIG.diamondSize, colors, node.label);
                    break;
                case 'fan_out':
                    renderTrapezoid(svg, pos.x, pos.y, w, h, colors, node.label, false);
                    break;
                case 'fan_in':
                    renderTrapezoid(svg, pos.x, pos.y, w, h, colors, node.label, true);
                    break;
                case 'gate':
                    renderOctagon(svg, pos.x, pos.y, w, h, colors, node.label);
                    break;
                default:
                    renderRect(svg, pos.x, pos.y, w, h, colors, node.label);
            }

            if (node.status !== 'definition') {
                renderStatusBadge(svg, pos.x, pos.y, w, h, node.status);
            }
        });

        var container = document.getElementById(containerId);
        if (container) {
            container.innerHTML = '';
            container.appendChild(svg);
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () {
            renderDiagram('dag-diagram', 'dag-graph-data');
        });
    } else {
        renderDiagram('dag-diagram', 'dag-graph-data');
    }

})();
