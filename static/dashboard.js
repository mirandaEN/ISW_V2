let datosFinancierosGlobales = [];
let datosTopActivosGlobales = [];
// --- ¡NUEVO ARREGLO DE MODO OSCURO! ---
// Esto se ejecuta INMEDIATAMENTE, antes de que se cargue el DOM.
// 1. Revisa el localStorage
const currentTheme = localStorage.getItem('theme');
// 2. Aplica la clase al <body> ANTES de que se dibuje nada
if (currentTheme === 'dark') {
    document.body.classList.add('dark-mode');
}
// --- FIN DEL ARREGLO ---

// Colores de texto para los modos
const colorTextoModoOscuro = '#f0f0f0';
const colorTextoModoClaro = '#343a40';

// --- 1. Define las variables de las gráficas globalmente ---
let chartFinanciero = null;
let chartTopActivos = null;

// --- 2. Función Principal para Dibujar TODO ---
function renderDashboard() {
    
    // --- Lógica de Color Inteligente ---
    const isDarkMode = document.body.classList.contains('dark-mode');
    const textColor = isDarkMode ? colorTextoModoOscuro : colorTextoModoClaro;
    const gridColor = isDarkMode ? 'rgba(255, 255, 255, 0.1)' : 'rgba(0, 0, 0, 0.1)';

    // --- 2a. Llenar la Tabla "WOW" (Solo se ejecuta la primera vez) ---
    const tbody = document.getElementById('tabla-predictiva');
    if (tbody && !tbody.innerHTML.trim()) { // Solo si la tabla está vacía
        fetch('/api/dashboard/predictivo')
            .then(response => response.json())
            .then(datos => {
                tbody.innerHTML = ''; // Limpiar por si acaso
                datos.forEach(item => {
                    let claseColor = '';
                    if (item.porcentaje_vida_consumida > 95) {
                        claseColor = 'table-danger-light';
                    } else if (item.porcentaje_vida_consumida > 80) {
                        claseColor = 'table-warning-light';
                    }
                    tbody.innerHTML += `
                        <tr class="${claseColor}">
                            <td>${item.nombre}</td>
                            <td>${item.tipo}</td>
                            <td>${item.horas_uso_acumuladas} hrs</td>
                            <td>${item.vida_util_estimada_horas} hrs</td>
                            <td><strong>${item.porcentaje_vida_consumida}%</strong></td>
                        </tr>
                    `;
                });
            })
            .catch(error => console.error('Error al cargar datos predictivos:', error));
    }

    // --- 2b. Llenar la Gráfica Financiera (Gráfica de Pastel) ---
    fetch('/api/dashboard/financiero')
        .then(response => response.json())
        .then(datos => {
            const ctx = document.getElementById('grafica-financiera').getContext('2d');
            if (chartFinanciero) {
                chartFinanciero.destroy(); // Destruye la gráfica vieja
            }
            chartFinanciero = new Chart(ctx, { // Dibuja la nueva
                type: 'doughnut',
                data: {
                    labels: datos.map(item => item.tipo),
                    datasets: [{
                        label: 'Valor del Stock ($ MXN)',
                        data: datos.map(item => item.valor_total_stock),
                    }]
                },
                options: {
                    plugins: {
                        legend: {
                            labels: {
                                color: textColor // ¡Color dinámico!
                            }
                        }
                    }
                }
            });
            datosFinancierosGlobales = datos; // Guardamos los datos
        })
        .catch(error => console.error('Error al cargar datos financieros:', error));

    // --- 2c. Llenar la Gráfica "Top 5 Activos" (Gráfica de Barras) ---
    fetch('/api/dashboard/top-activos')
        .then(response => response.json())
        .then(datos => {
            const ctx = document.getElementById('grafica-top-activos').getContext('2d');
            if (chartTopActivos) {
                chartTopActivos.destroy(); // Destruye la gráfica vieja
            }
            chartTopActivos = new Chart(ctx, { // Dibuja la nueva
                type: 'bar',
                data: {
                    labels: datos.map(item => item.nombre),
                    datasets: [{
                        label: 'Horas de Uso Acumuladas',
                        data: datos.map(item => item.horas_uso_acumuladas),
                        backgroundColor: [
                            'rgba(106, 90, 205, 0.7)',
                            'rgba(84, 153, 199, 0.7)',
                            'rgba(153, 163, 164, 0.7)',
                            'rgba(130, 126, 233, 0.7)',
                            'rgba(133, 193, 233, 0.7)'
                        ]
                    }]
                },
                options: {
                    indexAxis: 'y',
                    scales: {
                        x: {
                            ticks: { color: textColor }, // ¡Color dinámico!
                            grid: { color: gridColor }
                        },
                        y: {
                            ticks: { color: textColor }, // ¡Color dinámico!
                            grid: { color: gridColor }
                        }
                    },
                    plugins: {
                        legend: {
                            labels: {
                                color: textColor // ¡Color dinámico!
                            }
                        }
                    }
                }
            });
            datosTopActivosGlobales = datos; // Guardamos los datos
        })
        .catch(error => console.error('Error al cargar datos top 5:', error));
}


// --- 3. EVENT LISTENERS ---
document.addEventListener("DOMContentLoaded", () => {
    
    // Dibuja todo por primera vez (¡ahora el <body> SÍ tiene la clase correcta!)
    renderDashboard(); 

    // Botón de PDF (sin cambios)
    // --- 4. Funcionalidad del Botón PDF "Broche de Oro" ---

// Esta nueva función RELLENA el div oculto
async function prepararReporte() {
    
    // 1. Rellenar Fecha
    const fechaHoy = new Date().toLocaleString('es-MX', { dateStyle: 'long', timeStyle: 'short' });
    document.getElementById('pdf-fecha').textContent = fechaHoy;

    // 2. Rellenar Tabla de Alertas (Copiamos el HTML de la tabla visible)
    const tablaVisibleHead = document.querySelector("#tabla-predictiva").previousElementSibling; // El thead
    const tablaVisibleBody = document.getElementById('tabla-predictiva');
    document.getElementById('pdf-tabla-alertas-head').innerHTML = tablaVisibleHead.innerHTML;
    document.getElementById('pdf-tabla-alertas-body').innerHTML = tablaVisibleBody.innerHTML;

    // 3. Rellenar Listas (con los datos que guardamos)
    const listaFinanciero = document.getElementById('pdf-lista-financiero');
    listaFinanciero.innerHTML = ''; // Limpiar
    datosFinancierosGlobales.forEach(item => {
        // Formatear el número como moneda
        const valorMoneda = item.valor_total_stock.toLocaleString('es-MX', { style: 'currency', currency: 'MXN' });
        listaFinanciero.innerHTML += `<li><strong>${item.tipo}:</strong> ${valorMoneda}</li>`;
    });

    const listaTop5 = document.getElementById('pdf-lista-top5');
    listaTop5.innerHTML = ''; // Limpiar
    datosTopActivosGlobales.forEach(item => {
        listaTop5.innerHTML += `<li><strong>${item.nombre}:</strong> ${item.horas_uso_acumuladas} horas de uso</li>`;
    });

    // 4. ¡EL "WOW"! Generar el Texto Descriptivo
    const numAlertas = tablaVisibleBody.rows.length;
    let resumenTexto = `
        El presente reporte, generado el ${fechaHoy}, detalla el estado actual 
        del inventario y la utilización de activos en el laboratorio.
        <br><br>
        El análisis predictivo ha identificado <strong>${numAlertas} equipos en riesgo de falla</strong> 
        que requieren mantenimiento inmediato (detallados en la siguiente sección). 
        El valor total del inventario en stock (consumibles) está valorado en 
        ${datosFinancierosGlobales.reduce((acc, item) => acc + item.valor_total_stock, 0).toLocaleString('es-MX', { style: 'currency', currency: 'MXN' })}, 
        y el análisis de uso indica que los equipos más solicitados son los ${datosTopActivosGlobales[0].nombre}.
    `;
    document.getElementById('pdf-resumen-ejecutivo').innerHTML = resumenTexto;
}


// Esta es la función que se activa al hacer clic
document.getElementById('btn-descargar-pdf').addEventListener('click', async () => {
    
    // 1. Prepara el reporte oculto (¡NUEVO PASO!)
    await prepararReporte();

    // 2. Selecciona el 'div' OCULTO
    const elemento = document.getElementById('reporte-formal-pdf');
    
    // 3. Configura las opciones del PDF
    const opciones = {
        margin:       [0.5, 0.5, 0.5, 0.5], // Márgenes en cm (arriba, izq, abajo, der)
        filename:     'Reporte_Ejecutivo_Labflow.pdf',
        image:        { type: 'jpeg', quality: 0.98 },
        html2canvas:  { scale: 2 },
        jsPDF:        { unit: 'cm', format: 'letter', orientation: 'portrait' } // Vertical
    };

    // 4. ¡Genera y descarga el PDF!
    // Le decimos que muestre el div, lo imprima, y lo vuelva a ocultar
    elemento.style.display = 'block'; 
    await html2pdf().set(opciones).from(elemento).save();
    elemento.style.display = 'none';
});
});