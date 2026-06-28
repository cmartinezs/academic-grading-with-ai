Algoritmo ConsumoAgua
	Definir opcion, contador Como Entero
	Definir litros, total, promedio Como Real
	total <- 0
	contador <- 0
	Repetir
		Escribir "1. Registrar consumo"
		Escribir "2. Ver promedio"
		Escribir "3. Salir"
		Leer opcion
		Si opcion = 1 Entonces
			Escribir "Ingrese litros"
			Leer litros
			Si litros > 0 Entonces
				total <- total + litros
				contador <- contador + 1
			FinSi
		SiNo
			Si opcion = 2 Entonces
				Si contador > 0 Entonces
					promedio <- total / contador
					Escribir "Promedio: ", promedio
				SiNo
					Escribir "No hay registros"
				FinSi
			FinSi
		FinSi
	Hasta Que opcion = 3
FinAlgoritmo
